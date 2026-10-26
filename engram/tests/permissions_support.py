"""Test support for the permissions model: a World that writes table rows directly and checks nothing."""
import contextlib
import calendar
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import copy as _copy
import dataclasses
from typing import NamedTuple

from permissions import (ACTIONS, GRANT_OPS, Act, BulkUse, Grant, Record, State, Use, _row, _units, home_of,
                         parse_selector, selector_json)

SEED = 20261025
_OBJ = ("kinds", "stores", "layers", "lanes", "collections", "memories")


M1 = "mem:S/episode/m1"
M2, M3, M4 = "mem:S/episode/m2", "mem:S/episode/m3", "mem:S/episode/m4"
HOME = "place:home/andy"
CLINIC_3 = "place:la-county/public-health/clinic-3"
MEDICAL = "collection:andy/medical-history"


def T(text: str) -> int:
    """'2026-11-02' or '2026-12-15T00:00:00Z' to UTC seconds."""
    if "T" not in text:
        text += "T00:00:00Z"
    return calendar.timegm(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timetuple())


def _hex(tag: str, n: int) -> str:
    return hashlib.sha256(f"{tag}-{n}".encode()).hexdigest()[:32]


def _ref(prefix: str, v: str) -> str:
    return v if v.startswith(prefix) else prefix + v


class World:
    """Writes table rows with increasing seqs. Never refuses; fills what the ledger fills (PF12)."""

    def __init__(self, owner="andy", start=T("2026-11-01")):
        self.owner = _ref("person:", owner)
        self.now = start
        self.start = start
        self.seq = 0
        self.seq_at = {}
        self.rows = {}
        self.names = {}
        self._n = 0
        self.bulk_sets = []         # sets of objects a bulk use may name (P 6.4); random_world fills them
        self.cfg = None             # what random_world's samplers draw from
        self.meta = {"ledger_id": "ledger-test", "schema_version": "1", "owner": self.owner,
                     "admins": self.owner}
        self.person(self.owner, admin=True)

    # -- plumbing
    def _bump(self) -> int:
        self.seq += 1
        self.seq_at[self.seq] = self.now
        return self.seq

    def _add(self, table, **row):
        self.rows.setdefault(table, []).append(row)
        return row

    def _find(self, table, **match):
        for r in reversed(self.rows.get(table, [])):
            if all(r.get(k) == v for k, v in match.items()):
                return r
        raise KeyError((table, match))

    def _next(self, tag):
        self._n += 1
        return _hex(tag, self._n)

    # -- people and places
    def person(self, handle, admin=False):
        pid = _ref("person:", handle)
        seq = self._bump()
        home = home_of(pid)
        self._add("persons", id=pid, home=home, is_admin=int(admin), created_seq=seq)
        self._add("places", id=home, is_root=1, created_seq=seq,
                  pseudonym_salt=hashlib.sha256(home.encode()).digest()[:16])
        self._add("place_stewards", place=home, person=pid, added_seq=seq)

    def place(self, pid, parents=(), stewards=(), name=None):
        seq = self._bump()
        parents = list(parents)
        body = pid[len("place:"):]
        if not parents and "/" in body and not body.startswith("home/"):
            parents = ["place:" + body.rpartition("/")[0]]
        self._add("places", id=pid, is_root=int(not parents), created_seq=seq,
                  pseudonym_salt=hashlib.sha256(pid.encode()).digest()[:16])
        for q in parents:
            self._add("place_parents", place=pid, parent=q, added_seq=seq)
        for s in stewards:
            self._add("place_stewards", place=pid, person=_ref("person:", s), added_seq=seq)
        if name:
            self.names[pid] = name

    def add_parent(self, place, parent):
        self._add("place_parents", place=place, parent=parent, added_seq=self._bump())

    def places(self):
        return [r["id"] for r in self.rows.get("places", [])]

    def retire_place(self, pid):
        self._find("places", id=pid)["retired_seq"] = self._bump()

    def retire_person(self, handle):
        pid = _ref("person:", handle)
        seq = self._bump()
        row = self._find("persons", id=pid)
        row["retired_seq"] = seq
        self._find("places", id=row["home"])["retired_seq"] = seq

    def remove_steward(self, place, person):
        self._find("place_stewards", place=place, person=_ref("person:", person), removed_seq=None)[
            "removed_seq"] = self._bump()

    # -- agents, stores, groups, collections
    def agent(self, name, acts_for, at=None):
        """at is the place the agent is put in, not a time."""
        aid = _ref("agent:", name)
        seq = self._bump()
        self._add("agents", id=aid, acts_for=acts_for, created_seq=seq)
        if at:
            self._add("agent_places", agent=aid, place=at, added_seq=seq)
        return aid

    def store(self, instance_id, owner="person:andy", place="place:home/andy", name="engram", imprint_of=None):
        self._add("stores", instance_id=instance_id, name=name, owner=owner, place=place,
                  imprint_of=imprint_of, created_seq=self._bump())

    def group(self, gid, owner, members):
        seq = self._bump()
        gid = _ref("group:", gid)
        self._add("groups", id=gid, owner=owner, created_seq=seq)
        for m in members:
            self._add("group_members", group_id=gid, agent=m, added_seq=seq)

    def collect(self, cid, refs, backing="person"):
        seq = self._bump()
        if not any(r["id"] == cid for r in self.rows.get("collections", [])):
            self._add("collections", id=cid, owner="person:" + cid.split(":", 1)[1].split("/")[0],
                      created_seq=seq)
        for ref in refs:
            self._add("collection_members", collection=cid, object=ref, backing=backing, added_seq=seq,
                      added_by=self.owner)

    def uncollect(self, cid, ref):
        r = self._find("collection_members", collection=cid, object=ref, removed_seq=None)
        r["removed_seq"] = self._bump()
        r["removed_by"] = self.owner

    def subject(self, ref, subject, self_claimed=False):
        self._add("subjects", object=ref, subject=subject, added_seq=self._bump(), added_by=self.owner,
                  self_claimed=int(self_claimed))

    def copy(self, copy_ref, source_ref):
        self._add("copies", object=copy_ref, source=source_ref, added_seq=self._bump())

    def leave(self, agent):
        """The agent leaves the place it is in."""
        self._find("agent_places", agent=agent, removed_seq=None)["removed_seq"] = self._bump()

    def lane(self, ref, lane, at):
        self._add("lane_notes", object=ref, lane=lane, at=at, seq=self._bump())

    # -- records and grants
    def _record(self, effect, layer, kw):
        sel = {"audience": kw.pop("audience", ["self"]), "requesters": kw.pop("requesters", "*"),
               "objects": {k: kw.pop(k, "*") for k in _OBJ},
               "actions": kw.pop("actions", "*"), "purposes": kw.pop("purposes", "*")}
        if "kinds" not in kw and sel["objects"]["kinds"] == "*":
            sel["objects"]["kinds"] = ["memory"]
        rid = "r-" + self._next("record")
        seq = self._bump()
        row = dict(id=rid, layer=layer, effect=effect, selector=parse_selector(sel),
                   valid_from=self.start, valid_until=None, anchor=self.now, backing="person",
                   set_by=self.owner, channel="terminal", reason="test", created=self.now, created_seq=seq)
        row.update(kw)
        self._add("records", **row)
        return rid

    def allow(self, layer, **kw):
        return self._record("allow", layer, kw)

    def deny(self, layer, **kw):
        return self._record("deny", layer, kw)

    def record(self, rid) -> Record:
        return _row("records", self._find("records", id=rid))

    def revoke(self, rid):
        r = self._find("records", id=rid)
        r.update(revoked=self.now, revoked_by=self.owner, revoke_reason="test", revoked_seq=self._bump())

    def grant(self, issuer, grantee, layer, *, ops=("recall",), envelope="{}", parent_id=None, max_days=30,
              depth=0, expires=None):
        gid = "g-" + self._next("grant")
        seq = self._bump()
        self._add("permission_grants", id=gid, issuer=issuer, grantee=grantee, layer=layer,
                  parent_id=parent_id, ops=list(ops), envelope=envelope, max_days=max_days, depth=depth,
                  expires=self.now + 30 * 86400 if expires is None else expires, created=self.now,
                  created_seq=seq)
        return gid

    def grant_draft(self, *, issuer, grantee, layer, ops, envelope, max_days, depth, hours, parent_id=None,
                    gid=None) -> Grant:
        """A Grant that is not yet in the ledger, created now and lasting `hours`."""
        return Grant(id=gid or "g-" + self._next("grant"), issuer=issuer, grantee=grantee, layer=layer,
                     parent_id=parent_id, ops=frozenset(ops), envelope=envelope, max_days=max_days, depth=depth,
                     expires=self.now + hours * 3600, created=self.now, created_seq=self.seq + 1)

    def put_grant(self, g: Grant) -> Grant:
        seq = self._bump()
        g = dataclasses.replace(g, created_seq=seq)
        self._add("permission_grants", id=g.id, issuer=g.issuer, grantee=g.grantee, layer=g.layer,
                  parent_id=g.parent_id, ops=sorted(g.ops), envelope=selector_json(g.envelope),
                  max_days=g.max_days, depth=g.depth, expires=g.expires, created=g.created, created_seq=seq)
        return g

    def revoke_grant(self, gid):
        r = self._find("permission_grants", id=gid)
        r.update(revoked=self.now, revoked_by=self.owner, revoke_reason="test", revoked_seq=self._bump())

    def tick(self, seconds) -> int:
        self.now += seconds
        return self.now

    def state(self) -> State:
        return self.state_at(self.seq)

    def state_at(self, seq) -> State:
        """The State as of log sequence number `seq` (rows added later are dropped, later removals undone)."""
        tables = {t: [dict(r) for r in rs] for t, rs in self.rows.items()}
        return State.from_tables(tables, seq=seq, seq_at=self.seq_at, meta=self.meta, names=self.names)

    def fork(self) -> "World":
        """An independent copy, to which a test adds a layer, a subject or a change."""
        return _copy.deepcopy(self)


def random_dag_and_new_edge(rng):
    """A random DAG of 3 to 12 places and one new parent edge. Parents are always earlier places, so no
    cycle and at most 12 ancestors by construction; the edge goes from a place that already has a parent
    to an earlier place that is not yet its parent."""
    n = rng.randint(3, 12)
    w = World()
    ids = ["place:county"] + [f"place:county/p{i:02d}" for i in range(1, n)]
    w.place(ids[0])
    chosen = {}
    for i in range(1, n):
        k = rng.randint(1, min(4, i)) if i != 2 else 1
        chosen[i] = rng.sample(range(i), k)
        w.place(ids[i], parents=[ids[j] for j in chosen[i]])
    options = [(i, j) for i in range(2, n) for j in range(i) if j not in chosen[i] and len(chosen[i]) < 4]
    i, j = rng.choice(options)
    return w, ids[i], ids[j]


R1_ENVELOPE = parse_selector({
    "audience": ["place:la-county/public-health"], "requesters": "*",
    "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                "collections": ["collection:andy/medical-history"], "memories": "*"},
    "actions": ["recall", "read", "inject_context"], "purposes": ["care-coordination"]})


def widen_audience(envelope, place):
    return dataclasses.replace(envelope, audience=tuple(sorted({*envelope.audience, place}, key=_units)))


def county_world() -> World:
    """P 13's persons, places (names, stewards) and agents, and Andy's medical-history collection (PF20).
    No store, record, grant, lane note or Amy."""
    w = World()
    for handle in ("jenn", "county-steward", "ph-steward", "pr-steward", "sw-steward"):
        w.person(handle)
    w.place("place:la-county", stewards=["county-steward"], name="LA County")
    w.place("place:la-county/public-health", stewards=["ph-steward"], name="Public Health")
    w.place("place:la-county/parks-and-rec", stewards=["pr-steward"], name="Parks and Recreation")
    w.place("place:la-county/public-health/clinic-3", stewards=["ph-steward"])
    w.place("place:la-county/summer-wellness", parents=["place:la-county/public-health",
                                                       "place:la-county/parks-and-rec"],
            stewards=["sw-steward"], name="Summer Wellness")
    w.agent("rio-grande", "place:home/andy", at="place:home/andy")
    w.agent("ph-coordinator", "place:la-county/public-health/clinic-3",
            at="place:la-county/public-health/clinic-3")
    w.agent("parks-planner", "place:la-county/parks-and-rec", at="place:la-county/parks-and-rec")
    w.agent("sw-helper", "place:la-county/summer-wellness", at="place:la-county/summer-wellness")
    w.now = T("2026-10-01")
    w.collect("collection:andy/medical-history", [f"mem:S/episode/m{i}" for i in (1, 2, 3)])
    w.now = w.start
    return w


def child_draft(parent: Grant) -> Grant:
    """A grant one link below parent, from its grantee to another agent of the same person (unregistered
    if the test needs only the draft)."""
    grantee = "agent:rio-3" if parent.grantee == "agent:rio-2" else "agent:rio-2"
    return Grant(id="g-" + hashlib.sha256(parent.id.encode()).hexdigest()[:32], issuer=parent.grantee,
                 grantee=grantee, layer=parent.layer, parent_id=parent.id, ops=parent.ops,
                 envelope=parent.envelope, max_days=parent.max_days, depth=max(parent.depth - 1, 0),
                 expires=parent.expires, created=parent.created)


def three_link_chain():
    """(world, root, child, grandchild): Andy's root to rio-grande (depth 2), then rio-2 (1), then rio-3 (0)."""
    w = county_world()
    w.agent("rio-2", "place:home/andy", at="place:home/andy")
    w.agent("rio-3", "place:home/andy", at="place:home/andy")
    root = w.put_grant(w.grant_draft(
        issuer="person:andy", grantee="agent:rio-grande", layer="place:home/andy",
        ops={"share", "withdraw", "narrow"}, envelope=R1_ENVELOPE, max_days=120, depth=2, hours=720))
    child = w.put_grant(dataclasses.replace(
        child_draft(root), ops=frozenset({"share", "withdraw"}), max_days=60, expires=root.expires - 86400))
    child = dataclasses.replace(child, id=child.id)
    grandchild = w.put_grant(dataclasses.replace(
        child_draft(child), ops=frozenset({"share"}), max_days=30, expires=child.expires - 86400))
    return w, root, child, grandchild


def use(agent, place, obj, *, copy="store:house", action="recall", purpose="care-coordination", at=None,
        names=(), shows=()) -> Use:
    """A Use; `at` defaults to 2026-11-02."""
    return Use(requester=agent, place=place, obj=obj, copy=copy, action=action, purpose=purpose,
               at=T("2026-11-02") if at is None else at, names=tuple(names), shows=frozenset(shows))


def home_use(obj, at, **kw) -> Use:
    """Rio Grande, at Andy's home, on obj."""
    return use("agent:rio-grande", "place:home/andy", obj, at=at, **kw)


_PLACES = ["place:la-county", "place:la-county/public-health", "place:la-county/parks-and-rec",
           "place:la-county/public-health/clinic-3", "place:la-county/summer-wellness", "place:home/andy"]
_AGENTS = {"agent:rio-grande": "place:home/andy", "agent:ph-coordinator": "place:la-county/public-health/clinic-3",
           "agent:parks-planner": "place:la-county/parks-and-rec",
           "agent:sw-helper": "place:la-county/summer-wellness"}
_OBJS = ["mem:S/episode/m1", "mem:S/episode/m2", "mem:S/episode/m3", "mem:S/semantic/m4", "mem:Z/episode/m5",
         "road:S/r1"]
_PURPOSES = ["care-coordination", "research", "billing"]
_DAY = 86400


def _pick(rng, pool, star=0.4, kmax=3):
    if rng.random() < star:
        return "*"
    return rng.sample(pool, rng.randint(1, min(kmax, len(pool))))


def random_selector(rng) -> dict:
    """A selector document parse_selector accepts (R25 form: only a memory-only kinds list has object limits)."""
    aud = rng.sample(_PLACES + ["self", "commons", "group:andys"], rng.randint(1, 3))
    memory_only = rng.random() < 0.7
    objects = {"kinds": ["memory"] if memory_only else rng.choice([["memory", "road"], "*", ["road"]]),
               "stores": _pick(rng, ["S", "Z"], 0.6), "layers": "*", "lanes": "*", "collections": "*",
               "memories": "*"}
    if memory_only:
        objects["layers"] = _pick(rng, ["episode", "semantic"], 0.7, 2)
        objects["lanes"] = _pick(rng, ["personal", "work"], 0.6, 2)
        objects["collections"] = _pick(rng, ["collection:andy/medical-history", "collection:andy/other"], 0.6)
        objects["memories"] = _pick(rng, _OBJS[:5], 0.8)
    return {"audience": aud, "requesters": _pick(rng, list(_AGENTS), 0.6),
            "objects": objects, "actions": _pick(rng, ["recall", "read", "inject_context", "route", "imprint"],
                                                 0.3, 4),
            "purposes": _pick(rng, _PURPOSES, 0.5, 2)}


def random_replacement_chain(rng):
    """(world, [record ids]): an original allow and 1 to 3 replacements, each revoking the one before. The
    replacements' selectors and intervals are random, some outside the original's."""
    w = county_world()
    w.group("group:andys", "person:andy", ["agent:rio-grande"])
    w.collect("collection:andy/other", ["mem:S/episode/m1", "mem:S/semantic/m4"])
    chain, anchor = [], None
    for i in range(rng.randint(2, 4)):
        start = T("2026-11-01") + rng.randint(0, 30) * _DAY
        end = None if rng.random() < 0.3 else start + rng.randint(1, 60) * _DAY
        kw = {"valid_from": start, "valid_until": end}
        if chain:
            kw.update(replaces=chain[-1], anchor=anchor)
        doc = random_selector(rng)
        obj = doc.pop("objects")
        rid = w.allow("place:home/andy", audience=doc["audience"], requesters=doc["requesters"],
                      actions=doc["actions"], purposes=doc["purposes"], **obj, **kw)
        if not chain:
            anchor = w.now
        else:
            w.revoke(chain[-1])
        chain.append(rid)
        w.tick(rng.randint(0, 3) * _DAY)
    return w, chain


def apply_random_registry_changes(rng, w) -> None:
    """Random moves of memberships, lanes and placements, after the records are written."""
    base = T("2026-10-01")
    for ref in _OBJS[:5]:
        if rng.random() < 0.8:
            w.lane(ref, rng.choice(["personal", "work"]), base + rng.randint(0, 20) * _DAY)
        for _ in range(rng.randint(0, 3)):
            w.tick(rng.randint(0, 5) * _DAY)
            w.lane(ref, rng.choice(["pending", "personal", "work"]), w.now)
    for _ in range(rng.randint(0, 3)):
        w.tick(rng.randint(0, 5) * _DAY)
        coll = rng.choice(["collection:andy/medical-history", "collection:andy/other"])
        ref = rng.choice(_OBJS[:5])
        live = [r for r in w.rows.get("collection_members", []) if r["collection"] == coll
                and r["object"] == ref and r.get("removed_seq") is None]
        if live:
            w.uncollect(coll, ref)
        else:
            w.collect(coll, [ref])
    for agent in rng.sample(list(_AGENTS), rng.randint(0, 2)):
        w.tick(rng.randint(0, 5) * _DAY)
        w.leave(agent)
        if rng.random() < 0.5:
            w.tick(_DAY)
            w._add("agent_places", agent=agent, place=rng.choice(_PLACES), added_seq=w._bump())
    if rng.random() < 0.5:
        w.tick(_DAY)
        w._find("group_members", group_id="group:andys", agent="agent:rio-grande", removed_seq=None)[
            "removed_seq"] = w._bump()


def _sample_chain_uses(rng, w, n):
    """n random uses over the chain world's agents, places, objects and times."""
    out = []
    for _ in range(n):
        agent = rng.choice(list(_AGENTS))
        place = _AGENTS[agent] if rng.random() < 0.6 else rng.choice(_PLACES)
        out.append(use(agent, place, rng.choice(_OBJS), purpose=rng.choice(_PURPOSES), copy="store:S",
                       at=T("2026-10-20") + rng.randint(0, 100) * _DAY))
    return out


# ---------------------------------------------------------------- Task 5 builders (PF28: 5A reuses them)

def andy_world() -> World:
    """county_world plus Andy's store S and the published house `house`, both at his home."""
    w = county_world()
    w.store("S", owner="person:andy", place=HOME)
    w.store("house", owner="person:andy", place=HOME)
    return w


def _self_allow(w, actions=("recall",), **kw):
    return w.allow(HOME, audience=["self"], actions=list(actions), **kw)


def _case(w, obj=M1, at="2026-11-02", legacy=(), **kw):
    return w.state(), home_use(obj, T(at), **kw), tuple(legacy)


def unregistered_agent_use():
    w = andy_world()
    _self_allow(w)
    return w.state(), use("agent:ghost", HOME, M1, at=T("2026-11-02")), ()


def retired_subject_home_use():
    w = andy_world()
    w.subject(M1, "person:jenn")
    w.retire_person("jenn")
    _self_allow(w)
    return _case(w)


def no_subject_use():
    w = andy_world()
    _self_allow(w)
    return _case(w, obj="mem:Z/episode/m5")        # store Z has no `stores` row


def nine_subjects_use():
    w = andy_world()
    for i in range(8):
        w.person(f"p{i}")
        w.subject(M1, f"person:p{i}")
    _self_allow(w)
    return _case(w)


def dated_deny_use():
    w = andy_world()
    _self_allow(w)
    w.deny(HOME, audience=["self"], actions=["recall"], valid_from=T("2026-12-01"))
    return _case(w, at="2026-12-02")


def deny_naming_collection_before_its_anchor():
    """P 5.4: a deny reads a membership 'at any time in [anchor, t]', and that interval is empty for a use dated
    before the deny's anchor, so the deny does not match and the allow stands."""
    w = andy_world()
    w.collect(MEDICAL, [M1])
    _self_allow(w)
    w.deny(HOME, audience=["self"], actions=["recall"], anchor=T("2026-12-01"), collections=[MEDICAL])
    return [_case(w, at="2026-11-02")]


def ended_allow_use():
    w = andy_world()
    _self_allow(w, valid_until=T("2026-11-10"))
    return _case(w, at="2026-11-20")


def one_grant_backed_record(valid_from=None, valid_until=None, revoked_grant=False):
    """(state, u): one allow in Andy's home backed by a grant to rio-grande; u(at=...) is Rio Grande's recall of m1."""
    w = andy_world()
    envelope = parse_selector({
        "audience": ["self"], "requesters": "*",
        "objects": {k: ["memory"] if k == "kinds" else "*" for k in _OBJ},
        "actions": ["recall"], "purposes": "*"})
    g = w.put_grant(w.grant_draft(issuer="person:andy", grantee="agent:rio-grande", layer=HOME, ops={"share"},
                                  envelope=envelope, max_days=30, depth=0, hours=720))
    kw = {k: v for k, v in (("valid_from", valid_from), ("valid_until", valid_until)) if v is not None}
    _self_allow(w, backing=f"grant:{g.id}", **kw)
    if revoked_grant:
        w.revoke_grant(g.id)
    return w.state(), lambda at: home_use(M1, at)


def revoked_grant_use():
    s, u = one_grant_backed_record(revoked_grant=True)
    return s, u(T("2026-11-10")), ()


def future_allow_use():
    w = andy_world()
    _self_allow(w, valid_from=T("2026-12-01"))
    return _case(w, at="2026-11-20")


def silent_layer_use():
    return _case(andy_world())


def legacy_refusal_use():
    from permissions import LegacyLayer
    w = andy_world()
    _self_allow(w)
    return _case(w, legacy=[LegacyLayer("publisher", lambda u, x: False)])


def object_in_unregistered_store():
    s, u, _ = no_subject_use()
    return s, u


def placement_without_source_instance_id():
    w = andy_world()
    _self_allow(w)
    return w.state(), home_use("mem:/episode/m1", T("2026-11-02"))


def copy_in_unregistered_house():
    w = andy_world()
    _self_allow(w)
    return w.state(), home_use(M1, T("2026-11-02"), copy="store:ghost-house")


def one_ref_two_houses():
    """(state, at_home, at_clinic): Rio Grande imprints m1 into Andy's house, then into a house at clinic-3,
    whose layer allows nothing."""
    w = andy_world()
    w.store("clinic-house", owner="person:ph-steward", place=CLINIC_3)
    imprint = ["recall", "read", "imprint"]
    _self_allow(w, imprint)
    for place in ("place:la-county", "place:la-county/public-health"):
        w.allow(place, audience=["commons"], actions=imprint)
    at = T("2026-11-02")
    return (w.state(), home_use(M1, at, action="imprint", copy="store:house"),
            home_use(M1, at, action="imprint", copy="store:clinic-house"))


R1_ACTIONS = ["recall", "read", "inject_context"]


def _r1(w, **kw):
    fields = dict(audience=["place:la-county/public-health"], collections=[MEDICAL], actions=R1_ACTIONS,
                  purposes=["care-coordination"], valid_from=T("2026-11-01"), valid_until=T("2027-01-31"))
    return w.allow(HOME, **{**fields, **kw})


def co_subject_world(register_amy: bool):
    """(state, use): m1 has Amy as co-subject; ph-coordinator recalls it at clinic-3 under R1."""
    w = andy_world()
    if register_amy:
        w.person("amy")
    w.subject(M1, "person:amy")
    _r1(w)
    return w.state(), use("agent:ph-coordinator", CLINIC_3, M1, at=T("2026-11-02"))


def two_owner_imprint_use():
    """(world, use): station-imprints, for Andy at his home, imprints Sam's m1 into an imprint held at his home."""
    w = andy_world()
    w.person("sam")
    w.store("SAM", owner="person:sam", place="place:home/sam")
    w.store("c0a8", owner="person:andy", place=HOME, imprint_of="SAM")
    w.agent("station-imprints", HOME, at=HOME)
    imprint = ["recall", "read", "imprint"]
    w.allow("place:home/sam", audience=[HOME], stores=["SAM"], actions=imprint)
    w.allow(HOME, audience=["self"], stores=["S"], actions=imprint)         # Andy's own: none names Sam's store
    return w, use("agent:station-imprints", HOME, "mem:SAM/episode/m1", copy="imprint:peer-1/c0a8",
                  action="imprint", purpose="imprint-keep", at=T("2026-11-02"))


def sorted_actions(needs) -> tuple:
    """The actions the first need (the object) asks, in ACTIONS order."""
    from permissions import ACTIONS
    return tuple(a for a in ACTIONS if a in needs[0].actions)


def e1_world(through_use: int):
    """P 13 through the acts of use `through_use` (1 to 10). Uses 7 to 10 are ledger acts, at 11-05, 11-10,
    11-12 and 11-20; the others write nothing. Returns (World, ids)."""
    from permissions import KINDS
    w = andy_world()
    ids = SimpleNamespace(M1=M1, M2=M2, M3=M3, M4=M4, R1P=None, G1=None, D1=None)
    w.subject(M3, "person:jenn")
    w.now = T("2026-10-01")
    everything = list(KINDS)

    def rule(layer, audience, actions, purposes, until=None):
        return w.allow(layer, audience=[audience], kinds=everything, actions=actions, purposes=purposes,
                       valid_from=T("2026-10-01"), valid_until=until)
    ph, pr, sw = "place:la-county/public-health", "place:la-county/parks-and-rec", "place:la-county/summer-wellness"
    both = ["care-coordination", "program-operations"]
    ids.C1 = rule("place:la-county", "place:la-county", ["recall", "read", "inject_context", "route"], both,
                  T("2027-12-31"))
    ids.H1 = rule(ph, ph, R1_ACTIONS, ["care-coordination"])
    ids.H2 = rule(ph, sw, ["recall"], ["program-operations"])
    ids.K1 = rule(pr, pr, ["recall", "read", "inject_context", "route"], ["program-operations"])
    ids.K2 = rule(pr, sw, ["recall", "read"], ["program-operations"])
    ids.W1 = rule(sw, sw, ["recall", "read"], ["program-operations"])
    ids.L1 = rule(CLINIC_3, CLINIC_3, R1_ACTIONS, ["care-coordination"])
    w.now = w.start
    ids.R1 = _r1(w)
    ids.G1 = w.grant("person:andy", "agent:rio-grande", HOME, ops=["share", "withdraw", "shorten", "narrow", "collect",
                                                                    "uncollect"],
                     envelope=selector_json(R1_ENVELOPE), max_days=120, depth=0, expires=T("2026-11-30"))
    if through_use >= 7:
        w.now = T("2026-11-05")
        w.collect(MEDICAL, [M4], backing=f"grant:{ids.G1}")
    if through_use >= 8:
        w.now = T("2026-11-10")
        ids.R1P = _r1(w, valid_until=T("2026-12-15"), replaces=ids.R1, anchor=w.record(ids.R1).anchor,
                      set_by="agent:rio-grande", under_grant=ids.G1)
        w.revoke(ids.R1)
    if through_use >= 9:
        w.now = T("2026-11-12")
        ids.D1 = w.deny(HOME, audience=[ph], memories=[M2], valid_from=T("2026-12-01"))
    if through_use >= 10:
        w.now = T("2026-11-20")
        w.revoke_grant(ids.G1)
    return w, ids


def _ph_use(obj, at, action="recall"):
    return use("agent:ph-coordinator", CLINIC_3, obj, action=action, at=at)


def e1_use_1():
    w, _ = e1_world(1)
    return w.state(), _ph_use(M1, T("2026-11-02"), "inject_context")


E1_USE_1_LAYERS = ["place:home/andy", "place:la-county", "place:la-county/public-health", CLINIC_3]


def e1_use_1_with_publisher_rule_until(end: str):
    """E1's use 1 beside a legacy `publisher` rule that stops allowing at `end`: (state, u(at), legacy)."""
    from permissions import LegacyLayer
    w, _ = e1_world(1)
    stop = T(end)
    legacy = [LegacyLayer("publisher", lambda u, x: u.at < stop)]
    return w.state(), (lambda at: _ph_use(M1, at, "inject_context")), legacy


def e1_after_use_7():
    return e1_world(7)[0].state(), _ph_use


def e1_after_use_9():
    return e1_world(9)[0].state(), _ph_use


def e1_after_use_10():
    return e1_world(10)[0].state(), lambda at: _ph_use(M4, at, "read")


# ---------------------------------------------------------------- Task 5A: random_world and its samplers

class Bulk(NamedTuple):
    """A bulk use (P 6.4): one per-object use for each object of O, the same a, P, h, x, p and t. Until the
    evaluator decides one directly, it is allowed when every per-object use is."""
    uses: tuple


def use_json(u: Use) -> dict:
    """A Use as the plain dict the oracle reads."""
    return {"requester": u.requester, "place": u.place, "obj": u.obj, "copy": u.copy, "action": u.action,
            "purpose": u.purpose, "at": u.at, "names": list(u.names), "shows": sorted(u.shows)}


def legacy_json(legacy, u: Use) -> list:
    """PF29: [(name, {object: the actions the layer's callable allows for that object as a use})]. A callable can't
    be serialised, so it is asked of the use's object (as the use) and of each memory a road or trail names (as a
    use of its own, with no names), as `decide` asks it."""
    subs = {u.obj: u}
    for m in sorted(set(u.names) | set(u.shows)):
        subs.setdefault(m, dataclasses.replace(u, obj=m, names=(), shows=frozenset()))
    return [(layer.name, {o: frozenset(a for a in ACTIONS if layer.allows(x, a)) for o, x in subs.items()})
            for layer in legacy]


REQUIRED_FEATURES = frozenset({
    "op:share", "op:deny", "op:withdraw", "op:shorten", "op:narrow", "op:collect", "op:uncollect",
    "member:lane", "member:collection", "member:group", "member:agent_place", "member:place_parent",
    "joint", "root", "pending", "copy-chain-4", "bulk"})


def features(w: World) -> set:
    """Which of REQUIRED_FEATURES a world shows, read from its rows."""
    out, rows = set(), w.rows
    recs = rows.get("records", [])
    by_id = {r["id"]: r for r in recs}
    for r in recs:
        grant_backed = str(r["backing"]).startswith("grant:")
        if r["effect"] == "allow" and grant_backed and r.get("replaces") is None:
            out.add("op:share")
        if r["effect"] == "deny" and r.get("under_grant"):
            out.add("op:deny")
        if str(r.get("revoked_by") or "").startswith("agent:"):
            out.add("op:withdraw")
        old = by_id.get(r.get("replaces"))
        if old is not None and r.get("under_grant"):
            if r["selector"] != old["selector"]:
                out.add("op:narrow")
            elif r["valid_until"] is not None and (old["valid_until"] is None
                                                   or r["valid_until"] < old["valid_until"]):
                out.add("op:shorten")
    for m in rows.get("collection_members", []):
        out.add("member:collection")
        if str(m["backing"]).startswith("grant:"):
            out.add("op:collect")
        if m.get("removed_seq") is not None and str(m.get("removed_by") or "").startswith("agent:"):
            out.add("op:uncollect")
    notes = rows.get("lane_notes", [])
    if notes:
        out.add("member:lane")
    last = {}
    for n in sorted(notes, key=lambda n: (n["at"], n["seq"])):
        last[n["object"]] = n["lane"]
    if "pending" in last.values():
        out.add("pending")
    if rows.get("group_members"):
        out.add("member:group")
    if rows.get("agent_places"):
        out.add("member:agent_place")
    if rows.get("place_parents"):
        out.add("member:place_parent")
    count = {}
    for r in rows.get("place_parents", []):
        count[r["place"]] = count.get(r["place"], 0) + 1
    if any(k >= 2 for k in count.values()):
        out.add("joint")
    if any(p["is_root"] and not p["id"].startswith("place:home/") for p in rows.get("places", [])):
        out.add("root")
    links = {r["object"]: r["source"] for r in rows.get("copies", [])}
    for start in links:
        cur, hops = start, 0
        while cur in links and hops < 5:
            cur, hops = links[cur], hops + 1
        if hops >= 4:
            out.add("copy-chain-4")
    if w.bulk_sets:
        out.add("bulk")
    return out


DAY = _DAY
_KINDS_ALL = ["memory", "road", "trail"]
_RW_PURPOSES = ["care-coordination", "research", "billing"]
_COLLECTIONS = ["collection:andy/medical-history", "collection:andy/other", "collection:jenn/shared"]


def _doc_of(audience, *, requesters="*", actions="*", purposes="*", kinds=None, **dims) -> dict:
    objects = {"kinds": kinds or _KINDS_ALL, "stores": "*", "layers": "*", "lanes": "*", "collections": "*",
               "memories": "*"}
    objects.update(dims)
    return {"audience": list(audience), "requesters": requesters, "objects": objects, "actions": actions,
            "purposes": purposes}


def _kw_of(doc) -> dict:
    """A selector document as the keyword arguments of World.allow and World.deny."""
    out = {k: v for k, v in doc.items() if k != "objects"}
    out.update(doc["objects"])
    return out


def _rw_doc(rng, c, *, deny=False) -> dict:
    """A random selector document in R25 form (only a memory-only kinds list has object limits)."""
    entries, weights = ["commons", "self", "group:g1", "group:g2"] + c.places, None
    k = rng.randint(1, 3)
    aud = []
    for _ in range(k):
        r = rng.random()
        aud.append("commons" if r < 0.2 else "self" if r < 0.35 else rng.choice(["group:g1", "group:g2"])
                   if r < 0.45 else rng.choice(c.places))
    aud = sorted(set(aud))
    doc = _doc_of(aud, requesters=_pick(rng, c.agents, 0.6, 3), actions=_pick(rng, list(ACTIONS), 0.35, 4),
                  purposes=_pick(rng, _RW_PURPOSES, 0.5, 2))
    if rng.random() < 0.75:
        o = doc["objects"]
        o["kinds"] = ["memory"]
        o["stores"] = _pick(rng, c.store_ids, 0.6, 2)
        o["layers"] = _pick(rng, ["episode", "semantic"], 0.7, 1)
        o["lanes"] = _pick(rng, ["personal", "work"], 0.55, 1)
        o["collections"] = _pick(rng, _COLLECTIONS, 0.6, 2)
        o["memories"] = _pick(rng, c.objects, 0.75, 4)
    else:
        doc["objects"]["kinds"] = rng.choice([["road"], ["trail"], ["memory", "road"], _KINDS_ALL])
        doc["objects"]["stores"] = _pick(rng, c.store_ids, 0.5, 2)
    return doc


def _narrow(rng, doc, c) -> dict:
    """A document within `doc`: every list a sublist, a "*" a sublist of its pool."""
    d = _copy.deepcopy(doc)
    sub = lambda v: rng.sample(v, rng.randint(1, len(v)))
    d["audience"] = sub(d["audience"])
    pools = {"requesters": c.agents, "actions": list(ACTIONS), "purposes": _RW_PURPOSES}
    for k, pool in pools.items():
        d[k] = sub(d[k]) if d[k] != "*" else (sub(pool) if rng.random() < 0.4 else "*")
    o = d["objects"]
    if o["kinds"] == ["memory"]:
        opools = {"stores": c.store_ids, "layers": ["episode", "semantic"], "lanes": ["personal", "work"],
                  "collections": _COLLECTIONS, "memories": c.objects}
        for k, pool in opools.items():
            o[k] = sub(o[k]) if o[k] != "*" else (sub(pool) if rng.random() < 0.3 else "*")
    elif o["stores"] != "*":
        o["stores"] = sub(o["stores"])
    return d


def _grant_chain(w, rng, c, issuer, layer, holders):
    """A root grant to holders[0] and up to two children down the holders, each a subset of its parent."""
    n = rng.randint(1, len(holders))
    depth0 = rng.randint(n - 1, 2)
    hours = rng.randint(24, 720)
    ops = rng.sample(GRANT_OPS, rng.randint(3, len(GRANT_OPS)))
    doc = _narrow(rng, _rw_doc(rng, c), c) if rng.random() < 0.5 else _doc_of(["commons"])
    max_days = rng.randint(10, 120)
    expires = w.now + hours * 3600
    ids, docs, opss = [], [], []
    parent, issuer_of = None, issuer
    for i in range(n):
        gid = w.grant(issuer_of, holders[i], layer, ops=ops, envelope=selector_json(parse_selector(doc)),
                      parent_id=parent, max_days=max_days, depth=depth0 - i, expires=expires)
        ids.append(gid), docs.append(doc), opss.append(list(ops))
        parent, issuer_of = gid, holders[i]
        ops = rng.sample(ops, rng.randint(1, len(ops)))
        doc = _narrow(rng, doc, c)
        max_days = rng.randint(1, max_days)
        expires = w.now + rng.randint(12, max(12, (expires - w.now) // 3600)) * 3600
        w.tick(rng.randint(1, 600))
    return ids, docs, opss


def random_world(rng, *, places=12) -> World:
    """A World at a random point of its life. It reaches every grant op, every membership kind, joint places and
    roots, pending lane notes, kept copies with chains of 4 links, and bulk sets (P 18); its records are written
    without checks, as World writes everything. The shape of the draws is in `w.cfg`."""
    w = World()
    c = SimpleNamespace()
    w.cfg = c
    w.now = T("2026-10-01")
    homes = {h: f"place:home/{h}" for h in ("andy", "jenn", "sam", "st1", "st2", "late")}
    for h in list(homes)[1:]:
        w.person(h)
    # places: two roots and a DAG under them, with joint places
    ids = ["place:county", "place:elsewhere"] + [f"place:county/p{i:02d}" for i in range(2, places)]
    w.place(ids[0], stewards=["st1"])
    w.place(ids[1], stewards=["st2"])
    parents = {}
    for i in range(2, places):
        kmax = min(3, i - 1)
        k = min(kmax, 2 if i == 3 else rng.choice([1, 1, 2, 3]))
        parents[ids[i]] = rng.sample(ids[:i], k)
        w.place(ids[i], parents=parents[ids[i]], stewards=[rng.choice(["st1", "st2"])])
    c.places = ids
    c.parented = list(parents)
    c.earlier = {x: [q for q in ids[:ids.index(x)] if q not in parents[x]] for x in parents}
    # agents and groups
    c.agents, c.agent_history = [], {}

    def agent(name, acts_for, at):
        w.agent(name, acts_for, at=at)
        c.agents.append("agent:" + name)
        c.agent_history["agent:" + name] = [at]
    andy, jenn = homes["andy"], homes["jenn"]
    agent("a0", andy, andy)
    agent("a1", andy, rng.choice(ids))
    agent("a6", andy, andy)
    agent("a2", jenn, jenn)
    agent("a7", jenn, jenn)
    for k in (3, 4, 5):
        acts = rng.choice(ids)
        agent(f"a{k}", acts, acts if rng.random() < 0.7 else rng.choice(ids))
    w.group("group:g1", "person:andy", ["agent:a0", "agent:a1"])
    w.group("group:g2", "person:jenn", ["agent:a2"])
    # stores, houses, objects, roads and a chain of four kept copies
    w.store("S", owner="person:andy", place=andy)
    w.store("Z", owner="person:jenn", place=jenn)
    w.store("house", owner="person:andy", place=andy)
    w.store("H2", owner="person:st1", place=ids[2])
    w.store("I1", owner="person:sam", place=ids[3], imprint_of="S")
    c.store_ids = ["S", "Z", "house", "H2"]
    c.copies = ["store:S", "store:house", "store:H2", "imprint:peer-1/I1", "store:S", "store:house", "store:ghost"]
    mems = ["mem:S/episode/m1", "mem:S/episode/m2", "mem:S/episode/m3", "mem:S/semantic/m4",
            "mem:S/semantic/m5", "mem:Z/episode/m6", "mem:house/episode/m7", "mem:Q/episode/m8"]
    chain = [f"mem:H2/episode/c{i}" for i in range(1, 5)]
    for i, ref in enumerate(chain):
        w.copy(ref, mems[0] if i == 0 else chain[i - 1])
        w.subject(ref, "person:andy")                   # carried when the copy was made (P25)
    c.objects = mems + chain
    c.subjectable = [m for m in c.objects if not m.startswith("mem:Q/")]   # an object with no subject has ⊥
    c.copy_chain = chain[::-1] + [mems[0]]
    c.roads = {"road:S/r1": (mems[0], mems[1]), "road:S/r2": (mems[2], mems[3], mems[4]),
               "road:Z/r3": (mems[5], mems[0])}
    w.bulk_sets = [rng.sample(mems, rng.randint(2, 5)), list(c.roads) + rng.sample(mems, 2), list(chain)]
    # roads that name many memories, so the bound of 32 (P 6.4) is exercised: 40 is past it, 32 is the bound
    c.roads["road:S/r4"] = tuple(f"mem:S/episode/x{i}" for i in range(40))
    c.roads["road:S/r5"] = tuple(f"mem:S/episode/y{i}" for i in range(32))
    c.subject_pool = ["person:jenn", "person:sam", "person:andy", "person:late", "person:ghost", "place:county",
                      rng.choice(ids)]
    # October: collections, co-subjects and the first lane notes
    for cid in _COLLECTIONS:
        w.collect(cid, [m for m in mems if rng.random() < 0.5])
    for ref in mems:
        if rng.random() < 0.25:
            w.subject(ref, rng.choice(c.subject_pool[:5] if rng.random() < 0.9 else c.subject_pool))
    last_note = {}
    for ref in c.objects:
        if rng.random() < 0.12:
            continue
        at = T("2026-10-02") + rng.randint(0, 6) * DAY + rng.randint(0, 3600)
        w.lane(ref, rng.choice(["personal", "work"]), at)
        for _ in range(rng.randint(0, 2)):
            at += rng.randint(1, 5) * DAY + rng.randint(1, 3600)
            if rng.random() < 0.2:
                w.lane(ref, "pending", at)
                at += 2 * DAY + rng.randint(1, 3600)
            w.lane(ref, rng.choice(["personal", "work"]), at)
        last_note[ref] = at
    # November: grants, records and what agents did under them
    w.now = T("2026-10-13")
    docs, edges = {}, set()
    owner_of = {place: "person:" + h for h, place in homes.items()}

    def put(layer, doc, effect="allow", **kw):
        w.tick(rng.randint(1, 600))
        kw.setdefault("valid_from", T("2026-10-01") - rng.randint(0, 5) * DAY if rng.random() < 0.7
                      else w.now + rng.randint(0, 30) * DAY)
        if "valid_until" not in kw:
            kw["valid_until"] = None if rng.random() < 0.55 else kw["valid_from"] + rng.randint(5, 90) * DAY
        if layer in owner_of:
            kw.setdefault("set_by", owner_of[layer])
        rid = (w.allow if effect == "allow" else w.deny)(layer, **_kw_of(doc), **kw)
        docs[rid] = doc
        return rid

    chains = [(_grant_chain(w, rng, c, "person:andy", andy, ["agent:a0", "agent:a1", "agent:a6"]),
               ["agent:a0", "agent:a1", "agent:a6"], andy, "person:andy"),
              (_grant_chain(w, rng, c, "person:jenn", jenn, ["agent:a2", "agent:a7"]),
               ["agent:a2", "agent:a7"], jenn, "person:jenn")]
    c.grant_chains = [g[0][0] for g in chains]
    for pid in ids:
        if rng.random() < 0.85:
            put(pid, _doc_of(["commons"]), valid_from=T("2026-10-01"),
                valid_until=None if rng.random() < 0.8 else T("2026-12-01") + rng.randint(0, 30) * DAY)
        for _ in range(rng.choice([0, 0, 1])):
            put(pid, _rw_doc(rng, c), "deny")
    for h, place in homes.items():
        if rng.random() < 0.92:
            aud = ["commons"] if rng.random() < 0.6 else sorted({"self", rng.choice(ids), "group:g1"})
            put(place, _doc_of(aud), valid_from=T("2026-10-01"),
                valid_until=None if rng.random() < 0.85 else T("2026-12-01") + rng.randint(0, 30) * DAY)
        for _ in range(rng.randint(2, 5) if h in ("andy", "jenn") else rng.randint(0, 2)):
            put(place, _rw_doc(rng, c))
        for _ in range(rng.choice([0, 0, 1, 2])):
            put(place, _rw_doc(rng, c), "deny")
    for agent_id in c.agents:
        if rng.random() < 0.25:
            doc = _doc_of(["commons"], actions=_pick(rng, list(ACTIONS), 0.2, 3))
            put(agent_id, doc, "deny", valid_from=T("2026-10-01"))
    base = [rid for rid in docs if w.record(rid).layer in (andy, jenn) and w.record(rid).effect == "allow"]
    for (ids_, gdocs, opss), holders, layer, person in chains:
        for gid, gdoc, ops, holder in zip(ids_, gdocs, opss, holders):
            if "share" in ops:
                for _ in range(rng.randint(1, 2)):
                    rid = put(layer, _narrow(rng, gdoc, c), backing=f"grant:{gid}", set_by=holder,
                              under_grant=gid, valid_from=T("2026-10-10"))
                    base.append(rid)
            if "deny" in ops and rng.random() < 0.6:
                put(layer, _narrow(rng, gdoc, c), "deny", set_by=holder, under_grant=gid)
            if "collect" in ops and layer == andy:
                for ref in rng.sample(mems[:5], rng.randint(0, 2)):
                    w.tick(rng.randint(1, 3600))
                    w.collect(_COLLECTIONS[0], [ref], backing=f"grant:{gid}")
                    w._find("collection_members", collection=_COLLECTIONS[0], object=ref,
                            removed_seq=None)["added_by"] = holder
            if "uncollect" in ops and rng.random() < 0.5:
                live = [m for m in w.rows["collection_members"]
                        if m["collection"].startswith("collection:" + person[len("person:"):] + "/")
                        and m.get("removed_seq") is None]
                if live:
                    w.tick(rng.randint(1, 3600))
                    w.uncollect(live[0]["collection"], live[0]["object"])
                    live[0]["removed_by"] = holder
            for op in ("shorten", "narrow"):
                mine = [b for b in base if w.record(b).layer == layer]
                if op in ops and mine and rng.random() < 0.7:
                    old = rng.choice(mine)
                    rec = w.record(old)
                    if rec.revoked_seq is not None:
                        continue
                    new_doc = docs[old] if op == "shorten" else _narrow(rng, docs[old], c)
                    until = (rec.valid_until or T("2026-12-31")) - rng.randint(1, 20) * DAY
                    rid = put(layer, new_doc, replaces=old, anchor=rec.anchor, backing=rec.backing,
                              set_by=holder, under_grant=gid, valid_from=rec.valid_from,
                              valid_until=until if op == "shorten" or rng.random() < 0.5 else rec.valid_until)
                    w.tick(1)
                    w.revoke(old)
                    w._find("records", id=old)["revoked_by"] = holder
                    base.append(rid)
            mine = [b for b in base if w.record(b).layer == layer]
            if "withdraw" in ops and mine and rng.random() < 0.4:
                victim = rng.choice(mine)
                if w.record(victim).revoked_seq is None:
                    w.tick(rng.randint(1, 3600))
                    w.revoke(victim)
                    w._find("records", id=victim)["revoked_by"] = holder
    # November and later: the changes nobody checked
    w.now = max(w.now, T("2026-10-24"))
    c.t0 = max(r["anchor"] for r in w.rows["records"])      # no use is drawn before every record exists
    for _ in range(rng.randint(2, 6)):
        w.tick(rng.randint(1, 3) * DAY + rng.randint(1, 3600))
        kind = rng.choice(["lane", "lane", "group", "agent", "uncollect", "subject", "edge", "grant", "revoke"])
        if kind == "lane":     # the ledger writes a first note before a move (P 5.3): only a laned memory moves
            w.lane(rng.choice(sorted(last_note)), rng.choice(["personal", "work"]), w.now)
        elif kind == "group":
            live = [r for r in w.rows["group_members"] if r.get("removed_seq") is None]
            if live:
                rng.choice(live)["removed_seq"] = w._bump()
        elif kind == "agent":
            who = rng.choice(c.agents)
            if not any(r["agent"] == who and r.get("removed_seq") is None for r in w.rows["agent_places"]):
                continue
            w.leave(who)
            if rng.random() < 0.6:
                w.tick(DAY)
                where = rng.choice(ids)
                w._add("agent_places", agent=who, place=where, added_seq=w._bump())
                c.agent_history[who].append(where)
        elif kind == "uncollect":
            live = [r for r in w.rows["collection_members"] if r.get("removed_seq") is None]
            if live:
                w.uncollect(live[0]["collection"], live[0]["object"])
        elif kind == "subject":
            w.subject(rng.choice(c.objects), rng.choice(c.subject_pool[:5]))
        elif kind == "edge":
            x = rng.choice(c.parented)
            w.add_parent(x, rng.choice(c.earlier[x]))
            parents[x].append(w.rows["place_parents"][-1]["parent"])
            c.earlier[x] = [q for q in c.earlier[x] if q not in parents[x]]
            if not c.earlier[x]:
                c.parented.remove(x)
        elif kind == "grant" and chains:
            ids_ = chains[rng.randrange(len(chains))][0][0]
            w.revoke_grant(rng.choice(ids_))
        elif kind == "revoke":
            live = [r for r in w.rows["records"] if r.get("revoked_seq") is None]
            if live:
                w.revoke(rng.choice(live)["id"])
    if rng.random() < 0.25:
        w.tick(DAY)
        w.lane(rng.choice(sorted(last_note)), "pending", w.now)
    if rng.random() < 0.12:
        w.retire_place(ids[rng.randrange(6, len(ids))])
    if rng.random() < 0.08:
        w.retire_person("late")
    if not c.parented:
        c.parented = ["place:county/p02"]
        c.earlier["place:county/p02"] = []
    for r in w.rows["records"]:
        edges.update(v for v in (r["valid_from"], r["valid_until"]) if v is not None)
    for g in w.rows["permission_grants"]:
        edges.add(g["expires"])
    c.edges = sorted(e for e in edges if c.t0 <= e <= c.t0 + 80 * DAY) or [c.t0 + 20 * DAY]
    return w


def _place_at(w, agent, t):
    """Where the agent was at time t, read from the rows (None if nowhere)."""
    for r in w.rows.get("agent_places", []):
        if r["agent"] == agent and w.seq_at[r["added_seq"]] <= t and (
                r.get("removed_seq") is None or t < w.seq_at[r["removed_seq"]]):
            return r["place"]
    return None


def sample_uses(rng, w, n):
    """n random uses over the world's agents, places, objects and times. A random_world's include roads
    that name memories and bulk uses (Bulk)."""
    c = w.cfg
    if c is None:
        return _sample_chain_uses(rng, w, n)
    out = []

    def when():
        if rng.random() < 0.3:
            return max(c.t0, rng.choice(c.edges) + rng.choice([-1, 0, 0, 1]))
        return c.t0 + rng.randint(0, 75) * DAY + rng.randint(0, DAY - 1)

    def one(agent, place, obj, copy, action, purpose, at):
        names = c.roads.get(obj, ())
        shows = frozenset(m for m in names if rng.random() < 0.4)
        return Use(requester=agent, place=place, obj=obj, copy=copy, action=action, purpose=purpose, at=at,
                   names=tuple(names), shows=shows)

    for _ in range(n):
        agent = rng.choice(c.agents)
        copy, action, purpose, at = rng.choice(c.copies), rng.choice(ACTIONS), rng.choice(_RW_PURPOSES), when()
        place = _place_at(w, agent, at) if rng.random() < 0.85 else None
        place = place or rng.choice(c.places)
        if w.bulk_sets and rng.random() < 0.15:
            objs = sorted(rng.choice(w.bulk_sets))
            out.append(Bulk(tuple(one(agent, place, o, copy, action, purpose, at) for o in objs)))
        else:
            obj = rng.choice(c.objects + list(c.roads))
            out.append(one(agent, place, obj, copy, action, purpose, at))
    return out


# ---------------------------------------------------------------- Task 7: roads, trails and bulk uses

ROAD, TRAIL = "road:S/r1", "trail:S/t1"
RIO = "agent:rio-grande"
ALL_KINDS = ["memory", "road", "trail"]


def memories(n: int, start: int = 0) -> tuple:
    """n memory refs of store S, m<start> on."""
    return tuple(f"mem:S/episode/m{start + i}" for i in range(n))


def route(obj, names=(), shows=(), action="route"):
    """Rio Grande's answer use on a road or trail (a single use, so the bound of 32 applies)."""
    return home_use(obj, T("2026-11-02"), action=action, names=names, shows=shows)


def trail_use(obj, action, names=()):
    return home_use(obj, T("2026-11-02"), action=action, names=names)


def road_world():
    """Andy's home allows Rio Grande recall, read and route on memories, roads and trails, and inject_context
    on M1 only. (A road r names M1 and M2.)"""
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=ALL_KINDS, actions=["recall", "read", "route"])
    w.allow(HOME, audience=["self"], actions=["inject_context"], memories=[M1])
    return w.state()


def trail_world(blocked=None):
    w = andy_world()
    w.allow(HOME, audience=["self"], kinds=ALL_KINDS, actions=["recall", "read", "imprint", "route"])
    if blocked is not None:
        w.deny(HOME, audience=["self"], memories=[blocked], actions=["recall"])
    return w.state()


def bulk_use(objects, *, action="route", names=lambda o: (), named=False, requester=RIO, place=HOME,
             copy="store:house", purpose="care-coordination", at=None) -> BulkUse:
    return BulkUse(requester=requester, place=place, objects=tuple(objects), copy=copy, action=action,
                   purpose=purpose, at=T("2026-11-02") if at is None else at, named=named, names=names)


def trails_of(n: int, touches: int, *, same_memories=False):
    """(trail refs, names) for n derived trails of S: each names `touches` memories, the same ones or its own."""
    refs = tuple(f"trail:S/t{i}" for i in range(n))
    index = {r: i for i, r in enumerate(refs)}
    return refs, (lambda o: memories(touches, 0 if same_memories else index[o] * touches))


# ---------------------------------------------------------------- Task 8: the county's rules, and a joint past the cap

def e1_county_rules(extra=None) -> State:
    """C1, H1, H2, K1, K2, W1 and L1 of P 13 with the county's display names, and nothing else of Andy's
    story that matters to the gluing check. extra=(place, action) adds one more allow to that place's layer:
    the place itself, care-coordination, that one action."""
    from permissions import KINDS
    w, _ = e1_world(1)
    if extra:
        place, action = extra
        w.now = T("2026-10-01")
        w.allow(place, audience=[place], kinds=list(KINDS), actions=[action], purposes=["care-coordination"],
                valid_from=T("2026-10-01"))
        w.now = w.start
    return w.state()


def cap_world(n: int):
    """A county with a joint place whose own layer holds n allows, one box each (distinct memories).
    Returns (state, joint)."""
    w = World()
    w.person("st")
    w.place("place:big", stewards=["st"], name="Big")
    w.place("place:big/left", stewards=["st"], name="Left")
    w.place("place:big/right", stewards=["st"], name="Right")
    joint = "place:big/both"
    w.place(joint, parents=["place:big/left", "place:big/right"], stewards=["st"], name="Both")
    w.agent("worker", joint, at=joint)
    for i in range(n):
        w.allow(joint, audience=["commons"], memories=[f"mem:S/episode/c{i}"], actions=["recall"])
    return w.state(), joint


def cap_breaking_joint():
    """More than 4,096 boxes in one layer: (state, joint)."""
    return cap_world(4097)


# ---------------------------------------------------------------- Task 9: write rules, authority and words

PH = "place:la-county/public-health"
PR = "place:la-county/parks-and-rec"


def draft(**kw) -> Record:
    """A Record that is not yet in the ledger (R25 form: kinds default to memory). Defaults: an allow in Andy's
    home for `self`, every other dimension "*", from 2026-11-01, no end."""
    fields = dict(layer=HOME, effect="allow", valid_from=T("2026-11-01"), valid_until=None, backing="person",
                  set_by="person:andy", channel="terminal", under_grant=None, proposal_id=None, replaces=None,
                  reason="test", id="r-" + "0" * 32, revoked=None, revoked_by=None, revoke_reason=None,
                  revoked_seq=None, created_seq=0)
    for k in list(fields):
        if k in kw:
            fields[k] = kw.pop(k)
    sel = {"audience": kw.pop("audience", ["self"]), "requesters": kw.pop("requesters", "*"),
           "objects": {k: kw.pop(k, "*") for k in _OBJ},
           "actions": kw.pop("actions", "*"), "purposes": kw.pop("purposes", "*")}
    if sel["objects"]["kinds"] == "*":
        sel["objects"]["kinds"] = ["memory"]
    assert not kw, kw
    fields["anchor"] = fields["valid_from"]
    fields["created"] = fields["valid_from"]
    return _row("records", dict(fields, selector=parse_selector(sel)))


def allow(audience, layer=HOME) -> Record:
    return draft(layer=layer, audience=audience)


def layer_with_256_records():
    """(state, a 257th record) for Andy's home layer."""
    w = county_world()
    for i in range(256):
        w.allow(HOME, audience=["self"], actions=["recall"], memories=[f"mem:S/episode/c{i}"])
    return w.state(), draft(audience=["self"], actions=["recall"])


def object_with_8_subjects():
    """(state, ref): Andy (the store's owner) and seven co-subjects."""
    w = county_world()
    w.store("S", owner="person:andy", place=HOME)
    for i in range(1, 8):
        w.subject(M1, f"person:p{i}")
    return w.state(), M1


def collection_with_100000_members():
    w = county_world()
    w.collect("collection:andy/big", [f"mem:S/episode/b{i}" for i in range(100_000)])
    return w.state(), "collection:andy/big"


def mapping_world() -> State:
    w = county_world()
    for g in ("g1", "g2"):
        w.group(g, "person:andy", ["agent:rio-grande"])
    return w.state()


def e1_state_with_r1() -> State:
    return e1_world(1)[0].state()


R1 = e1_world(1)[1].R1


def parks_proposal_body(reason="because") -> dict:
    """The body of an agent's proposal to share the medical history with Parks and Recreation."""
    sel = dataclasses.replace(R1_ENVELOPE, audience=(PR,))
    return {"layer": HOME, "selector": selector_json(sel), "valid_from": T("2026-11-01"),
            "valid_until": T("2027-01-31"), "reason": reason}


U4_ACTORS = ("andy", "steward", "valid", "expired", "revoked", "too-deep", "none", "jenn")
_U4_WHO = {"andy": "person:andy", "steward": "person:ph-steward", "jenn": "person:jenn"}
U4_NEW_END = T("2026-12-15")


def channel_of(actor: str) -> str:
    return "terminal" if actor.startswith("person:") else "tool"


class _Ids(NamedTuple):
    grant: str
    r1: str
    own: str
    rph: str
    deny: str
    deny_ph: str


def u4_world(variant: str):
    """Andy's home with R1, an allow rio-grande wrote under a grant, a deny, and a PH layer with an allow and a
    deny. `variant` says what rio-grande holds: a valid grant (depth 1), an expired one, a revoked one, the
    fourth link of a chain, or none. Returns (state, ids)."""
    w = andy_world()
    w.agent("rio-2", HOME, at=HOME)
    w.agent("rio-3", HOME, at=HOME)
    w.agent("rio-4", HOME, at=HOME)
    w.group("group:g1", "person:andy", ["agent:rio-grande"])
    env = selector_json(R1_ENVELOPE)
    ops = list(GRANT_OPS)
    expires = T("2026-11-03") if variant == "expired" else None
    if variant in ("valid", "expired", "revoked"):
        gid = w.grant("person:andy", RIO, HOME, ops=ops, envelope=env, max_days=120, depth=1, expires=expires)
    elif variant == "too-deep":
        g1 = w.grant("person:andy", "agent:rio-2", HOME, ops=ops, envelope=env, max_days=120, depth=2)
        g2 = w.grant("agent:rio-2", "agent:rio-3", HOME, ops=ops, envelope=env, max_days=120, depth=1,
                     parent_id=g1)
        g3 = w.grant("agent:rio-3", "agent:rio-4", HOME, ops=ops, envelope=env, max_days=120, depth=0,
                     parent_id=g2)
        gid = w.grant("agent:rio-4", RIO, HOME, ops=ops, envelope=env, max_days=120, depth=0, parent_id=g3)
    else:
        gid = "g-" + "f" * 32           # none held; the allow rio-grande once wrote names a grant that is gone
    r1 = _r1(w)
    own = _r1(w, backing=f"grant:{gid}", set_by=RIO, under_grant=gid)
    ph_rule = dict(audience=[PH], kinds=list(KINDS_ALL), actions=R1_ACTIONS, purposes=["care-coordination"])
    rph = w.allow(PH, **ph_rule, set_by="person:ph-steward")
    deny = w.deny(HOME, audience=[PH], memories=[M2], actions=["recall", "read"])
    deny_ph = w.deny(PH, audience=[PH], memories=[M2], actions=["recall", "read"], set_by="person:ph-steward")
    if variant == "revoked":
        w.revoke_grant(gid)
    return w.state(), _Ids(gid, r1, own, rph, deny, deny_ph)


KINDS_ALL = ("memory", "road", "trail")


def u4_case(column: str, row: str):
    """(state, actor id, Act) for one cell of P 7.1. The steward acts in the Public Health layer; the others
    in Andy's home."""
    from permissions import Act
    s, ids = u4_world(column if column in ("valid", "expired", "revoked", "too-deep") else "none")
    actor = _U4_WHO.get(column, RIO)
    steward = column == "steward"
    layer = PH if steward else HOME
    rec = ids.rph if steward else ids.r1
    deny = ids.deny_ph if steward else ids.deny
    narrower = dataclasses.replace(s.records[rec].selector, actions=("recall",))
    deny_narrower = dataclasses.replace(s.records[deny].selector, actions=("recall",))
    args = {
        "allow": dict(layer=layer, selector=R1_ENVELOPE, valid_from=T("2026-11-01"), valid_until=T("2026-12-01")),
        "deny": dict(layer=layer, selector=R1_ENVELOPE, valid_from=T("2026-11-01"), valid_until=None),
        "withdraw": dict(record=rec),
        "withdraw-own": dict(record=rph_or(ids, steward)),
        "shorten": dict(record=rec, valid_until=U4_NEW_END),
        "narrow": dict(record=rec, selector=narrower),
        "revoke-deny": dict(record=deny),
        "shorten-deny": dict(record=deny, valid_until=U4_NEW_END),
        "narrow-deny": dict(record=deny, selector=deny_narrower),
        "collect": dict(collection=MEDICAL, objects=[M4]),
        "uncollect": dict(collection=MEDICAL, objects=[M1]),
        "add-subject": dict(object=M2, subject="person:amy"),
        "group": dict(group="group:g1", owner="person:andy"),
        "grant-root": dict(layer=layer, grantee="agent:rio-2", envelope=R1_ENVELOPE),
        "grant-child": dict(layer=HOME, grantee="agent:rio-2", parent=ids.grant),
        "give-up": dict(grant=ids.grant),
    }[row]
    kind = {"withdraw-own": "withdraw", "grant-root": "grant", "grant-child": "grant",
            "give-up": "give-up-grant"}.get(row, row)
    return s, actor, Act(kind, args)


def rph_or(ids, steward):
    return ids.rph if steward else ids.own


# expected, by column: andy, steward, valid, expired, revoked, too-deep, none, jenn (P 7.1, written by hand)
_D, _P, _R = "do", "proposal", "refused"
U4_EXPECTED = {
    "allow":        (_D, _D, _D, _P, _P, _P, _P, _R),
    "deny":         (_D, _D, _D, _R, _R, _R, _R, _R),
    "withdraw":     (_D, _D, _D, _R, _R, _R, _R, _R),
    "withdraw-own": (_D, _D, _D, _D, _D, _D, _D, _R),
    "shorten":      (_D, _D, _D, _P, _P, _P, _P, _R),
    "narrow":       (_D, _D, _D, _P, _P, _P, _P, _R),
    "revoke-deny":  (_D, _D, _P, _P, _P, _P, _P, _R),
    "shorten-deny": (_D, _D, _P, _P, _P, _P, _P, _R),
    "narrow-deny":  (_D, _D, _P, _P, _P, _P, _P, _R),
    "collect":      (_D, _R, _D, _P, _P, _P, _P, _R),
    "uncollect":    (_D, _R, _D, _P, _P, _P, _P, _R),
    "add-subject":  (_D, _R, _D, _D, _D, _D, _D, _R),
    "group":        (_D, _R, _P, _P, _P, _P, _P, _R),
    "grant-root":   (_D, _D, _P, _P, _P, _P, _P, _R),
    "grant-child":  (_R, _R, _D, _R, _R, _R, _R, _R),
    "give-up":      (_R, _R, _D, _D, _D, _D, _R, _R),
}
U4_TABLE = [(column, row, expected) for row, cells in U4_EXPECTED.items()
            for column, expected in zip(U4_ACTORS, cells)]


# ---------------------------------------------------------------- Task 11: ledgers built through `perform`

SW = "place:la-county/summer-wellness"
COUNTY = "place:la-county"
STORE_S, STORE_HOUSE, STORE_K = "S", "HOUSE", "K"
M5, M6 = "mem:S/episode/m5", "mem:S/episode/m6"
COPY_OF_M3 = "mem:K/episode/c3"
ANDY = "person:andy"


def do(led, actor, kind, now="2026-11-01", channel="terminal", **args):
    """One act through Ledger.perform, as `actor`, on channel `terminal` unless told otherwise."""
    return led.perform(Act(kind, args), actor=actor, channel=channel, now=T(now))


def county_ledger(tmp_path):
    """P 13's county, its people and its agents, every row through `perform`. No store and no record."""
    from permission_ledger import Ledger
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    for handle in ("county-steward", "ph-steward", "pr-steward", "sw-steward", "sw2", "jenn", "amy"):
        do(led, ANDY, "register-person", person="person:" + handle)
    do(led, ANDY, "register-place", place=COUNTY, name="LA County", stewards=["person:county-steward"])
    do(led, "person:county-steward", "register-place", place=PH, name="Public Health",
       stewards=["person:ph-steward"])
    do(led, "person:county-steward", "register-place", place=PR, name="Parks and Recreation",
       stewards=["person:pr-steward"])
    do(led, "person:ph-steward", "register-place", place=CLINIC_3, stewards=["person:ph-steward"])
    do(led, "person:ph-steward", "register-agent", agent="agent:ph-coordinator", acts_for=CLINIC_3)
    do(led, "person:ph-steward", "put-agent", agent="agent:ph-coordinator", place=CLINIC_3)
    do(led, "person:pr-steward", "register-agent", agent="agent:parks-planner", acts_for=PR)
    do(led, "person:pr-steward", "put-agent", agent="agent:parks-planner", place=PR)
    do(led, "person:pr-steward", "register-agent", agent="agent:parks-intern", acts_for=PR)
    do(led, ANDY, "register-agent", agent="agent:rio-grande", acts_for=HOME)
    do(led, ANDY, "put-agent", agent="agent:rio-grande", place=HOME)
    return led


def e1_ledger_through_andys_side(tmp_path):
    """county_ledger, Andy's stores and collection, then R1 and G1 of P 13 through `perform`. The ids are on
    `led.ids`."""
    led = county_ledger(tmp_path)
    for iid, name in ((STORE_S, "engram"), (STORE_HOUSE, "published house"), (STORE_K, "keeper store")):
        do(led, ANDY, "register-store", instance_id=iid, name=name, owner=ANDY, place=HOME, imprint_of=None)
    do(led, ANDY, "make-collection", collection=MEDICAL)
    personal = {"lane": "personal", "created_at": T("2026-10-01")}
    do(led, ANDY, "collect", collection=MEDICAL, refs=[M1, M2, M3], lanes={r: personal for r in (M1, M2, M3)})
    do(led, ANDY, "add-subject", object=M3, subject="person:jenn")
    ids = SimpleNamespace(M1=M1, M2=M2, M3=M3, M4=M4, M5=M5, M6=M6)
    ids.R1 = do(led, ANDY, "allow", layer=HOME, selector=R1_ENVELOPE, valid_from=T("2026-11-01"),
                valid_until=T("2027-01-31"), reason="R1").ref
    ids.G1 = do(led, ANDY, "grant", layer=HOME, grantee="agent:rio-grande", ops=[
        "share", "withdraw", "shorten", "narrow", "collect", "uncollect"], envelope=R1_ENVELOPE, max_days=120,
        depth=0, hours=29 * 24).ref                          # expires 2026-11-30
    led.ids = ids
    return led


def e1_county_ledger(tmp_path):
    """e1_ledger_through_andys_side, the joint place and P 13's county records C1, H1, H2, K1, K2, W1, L1."""
    from permission_ledger import new_id
    led = e1_ledger_through_andys_side(tmp_path)
    filed = do(led, "person:ph-steward", "register-place", place=SW, parents=[PH, PR], name="Summer Wellness",
               stewards=["person:sw-steward"])
    do(led, "person:pr-steward", "sign", proposal=filed.ref)
    do(led, "person:sw-steward", "register-agent", agent="agent:sw-helper", acts_for=SW)
    do(led, "person:sw-steward", "put-agent", agent="agent:sw-helper", place=SW)
    at, ids = T("2026-11-01"), led.ids
    both = ["care-coordination", "program-operations"]
    rules = [("C1", "person:county-steward", COUNTY, COUNTY, ["recall", "read", "inject_context", "route"], both,
              T("2027-12-31")),
             ("H1", "person:ph-steward", PH, PH, R1_ACTIONS, ["care-coordination"], None),
             ("H2", "person:ph-steward", PH, SW, ["recall"], ["program-operations"], None),
             ("K1", "person:pr-steward", PR, PR, ["recall", "read", "inject_context", "route"],
              ["program-operations"], None),
             ("K2", "person:pr-steward", PR, SW, ["recall", "read"], ["program-operations"], None),
             ("W1", "person:sw-steward", SW, SW, ["recall", "read"], ["program-operations"], None),
             ("L1", "person:ph-steward", CLINIC_3, CLINIC_3, R1_ACTIONS, ["care-coordination"], None)]
    for name, steward, layer, audience, actions, purposes, until in rules:
        rid = new_id("r-")
        setattr(ids, name, rid)
        sel = parse_selector(_doc_of([audience], actions=actions, purposes=purposes))
        led._append("allow", rid, steward, "terminal", {"insert": [{"table": "records", "row": {
            "id": rid, "layer": layer, "effect": "allow", "selector": selector_json(sel),
            "valid_from": T("2026-10-01"), "valid_until": until, "anchor": at, "backing": "person",
            "set_by": steward, "channel": "terminal", "reason": name, "created": at,
            "created_seq": "@seq"}}]}, at=at)
    return led


def copies_ledger(tmp_path, chain):
    """county_ledger, stores K0 to K5 at Andy's home, and `chain` copies c1 <- ... made with record_copy."""
    led = county_ledger(tmp_path)
    for i in range(6):
        do(led, ANDY, "register-store", instance_id=f"K{i}", name=f"keeper {i}", owner=ANDY, place=HOME,
           imprint_of=None)
    for i in range(1, chain + 1):
        led.record_copy(f"mem:K{i}/episode/c{i}", f"mem:K{i - 1}/episode/c{i - 1}", now=T("2026-11-02"))
    return led


def add_subject(led, ref, subject, *, actor, channel="terminal", self_claimed=False, now="2026-11-03"):
    out = do(led, actor, "add-subject", now=now, channel=channel, object=ref, subject=subject)
    if self_claimed:
        assert [r for r in led.state().subjects[ref] if r.subject == subject][-1].self_claimed
    return out


def remove_subject(led, ref, subject, *, actor, channel="terminal", now="2026-11-03"):
    return do(led, actor, "remove-subject", now=now, channel=channel, object=ref, subject=subject)


def read_by_ph(obj, at):
    """ph-coordinator, at clinic-3, reads obj from the published house."""
    return use("agent:ph-coordinator", CLINIC_3, obj, copy=f"store:{STORE_HOUSE}", action="read", at=at)


def source_with_copy_at_8_subjects(led):
    """(source, copy): the source has 7 subjects (Andy and six co-subjects); its copy, kept by sw2, holds 8."""
    src, copy = "mem:S/episode/m7", "mem:K9/episode/c7"
    for i in range(1, 7):
        add_subject(led, src, f"person:p{i}", actor=ANDY)
    do(led, "person:sw2", "register-store", now="2026-11-03", instance_id="K9", name="sw2 keeper",
       owner="person:sw2", place="place:home/sw2", imprint_of=None)
    led.record_copy(copy, src, now=T("2026-11-03"))
    return src, copy


def read_copy(copy):
    """Rio Grande reads the kept copy from its keeper's store."""
    return use("agent:rio-grande", HOME, copy, copy="store:K9", action="read", at=T("2026-11-05"))


# ---------------------------------------------------------------- Task 12: records, grants and proposals

def e1_ledger_with_g1(tmp_path):
    """Andy's side of P 13 with R1 and G1 written: R1 (person-backed) and G1 (rio-grande's grant) are on `led.ids`."""
    return e1_ledger_through_andys_side(tmp_path)


def parks_body() -> dict:
    """The arguments of rio-grande's try to add parks-and-rec to R1 (E1 use 6): outside G1's envelope."""
    return parks_proposal_body()


def selector_of(**changes):
    """R1's envelope with some fields replaced."""
    return dataclasses.replace(R1_ENVELOPE, **changes)


def d1_selector():
    """D1 of E1 use 9: public health, memory m2, any action and purpose."""
    return parse_selector({
        "audience": ["place:la-county/public-health"], "requesters": "*",
        "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": "*",
                    "memories": [M2]},
        "actions": "*", "purposes": "*"})


def e1_through_use_9(tmp_path):
    """e1_county_ledger (Andy's side, G1 and the county's rules), then through `perform`: a share by rio-grande
    under G1 (11-04), m4 collected under G1 (use 7, 11-05), R1 shortened to R1' (use 8, 11-10) and Andy's deny D1
    (use 9, 11-12). `ids` gains SHARE, R1P and D1. Returns (ledger, ids)."""
    led = e1_county_ledger(tmp_path)
    ids = led.ids
    share = do(led, RIO, "allow", now="2026-11-04", channel="tool", layer=HOME,
               selector=selector_of(audience=(CLINIC_3,), actions=("recall", "read")),
               valid_from=T("2026-11-04"), valid_until=T("2026-12-01"), reason="share with clinic-3")
    ids.SHARE = share.ref
    do(led, RIO, "collect", now="2026-11-05", channel="tool", collection=MEDICAL, objects=[M4])
    ids.R1P = do(led, RIO, "shorten", now="2026-11-10", channel="tool", record=ids.R1,
                 valid_until=T("2026-12-15")).ref
    ids.D1 = do(led, ANDY, "deny", now="2026-11-12", layer=HOME, selector=d1_selector(),
                valid_from=T("2026-12-01"), valid_until=None, reason="tell my doctor first").ref
    return led, ids


def only_proposal_rows_changed(before: dict, after: dict) -> bool:
    """Of two `Ledger.tables()`, only the log and the proposals differ."""
    return all(before[t] == after[t] for t in before if t not in ("ledger_log", "proposals"))


R26_SAMPLE_ACTS = [
    Act("register-place", {"place": "place:andy-lab", "stewards": ["person:andy"], "name": "Andy's Lab"}),
    Act("register-place", {"place": "place:andy-lab/x", "parents": ["place:andy-lab"],
                           "stewards": ["person:andy"]}),
    Act("register-place", {"place": "place:andy-other", "stewards": ["person:andy"]}),
    Act("add-parent", {"place": "place:andy-lab/x", "parent": "place:andy-other"}),
    Act("add-steward", {"place": "place:andy-lab", "person": "person:jenn"}),
    Act("register-agent", {"agent": "agent:rio-2", "acts_for": HOME}),
    Act("put-agent", {"agent": "agent:rio-2", "place": "place:andy-lab"}),
    Act("group", {"group": "group:g1", "owner": "person:andy", "members": ["agent:rio-grande"]}),
    Act("register-store", {"instance_id": "Q", "name": "q", "owner": "person:andy", "place": HOME}),
    Act("remove-subject", {"object": M3, "subject": "person:jenn"}),
    Act("collect", {"collection": MEDICAL, "objects": [M4]}),      # G1 has expired by then: no grant covers it
    Act("grant", {"layer": HOME, "grantee": "agent:rio-2", "ops": ["share"], "envelope": R1_ENVELOPE,
                  "max_days": 30, "depth": 0, "hours": 24}),
]


def applied(state: State, act: Act) -> bool:
    """Did `act` (one of R26_SAMPLE_ACTS) take effect in `state`?"""
    a = act.args
    live = lambda rows: [r for r in rows if r.removed_seq is None]
    if act.kind == "grant":
        return any(g.grantee == a["grantee"] and g.layer == a["layer"] for g in state.grants.values())
    if act.kind == "group":
        return {r.agent for r in live(state.group_members.get(a["group"], ()))} == set(a["members"])
    if act.kind == "register-agent":
        return a["agent"] in state.agents
    if act.kind == "put-agent":
        return any(r.place == a["place"] for r in live(state.agent_places.get(a["agent"], ())))
    if act.kind == "add-steward":
        return any(r.person == a["person"] for r in live(state.place_stewards.get(a["place"], ())))
    if act.kind == "register-place":
        return a["place"] in state.places
    if act.kind == "add-parent":
        return a["parent"] in [r.parent for r in state.place_parents.get(a["place"], ())]
    if act.kind == "register-store":
        return a["instance_id"] in state.stores
    if act.kind == "remove-subject":
        return not any(r.subject == a["subject"] for r in live(state.subjects.get(a["object"], ())))
    if act.kind == "collect":
        rows = live(state.collection_members.get(a["collection"], ()))
        return all(any(r.object == o and r.backing == "person" for r in rows) for o in a["objects"])
    raise AssertionError(act.kind)


# ---------------------------------------------------------------- the gate and the houses (Task 13; PF28)

def _house_path(root, name):
    from pathlib import Path
    base = Path(root) / ".engram"
    return base / "graph.db" if name is None else base / "instances" / name / "graph.db"


def make_house(root, name="lighthouse"):
    """An engram store file with only its `meta` table: `.engram/instances/<name>/graph.db`, or the default store
    `.engram/graph.db` for name None. Returns its path."""
    import sqlite3
    path = _house_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.commit()
    con.close()
    return path


def make_house_with_029(root, name="lighthouse"):
    """A house that has run migration 029: shared_memories with source_instance_id and record_id, and the
    shared_memories_changes table."""
    import sqlite3
    path = make_house(root, name)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE shared_memories (id TEXT PRIMARY KEY, source_instance_id TEXT, record_id TEXT)")
    con.execute("CREATE TABLE shared_memories_changes (counter INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    return path


def house_meta(path) -> dict:
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()


def raise_gate(led, mode, now="2026-11-02"):
    return do(led, ANDY, "gate", now=now, mode=mode)


def raised_ledger(root, houses=("lighthouse",), mode="shadow"):
    """A ledger at `root` whose gate is raised to `mode` over the named houses (made first)."""
    from permission_ledger import Ledger
    led = Ledger.create(root, "andy", now=T("2026-11-01"))
    for name in houses:
        make_house(root, name)
    raise_gate(led, mode)
    return led


def fresh_raised(root):
    """`raised_ledger` over the lighthouse and one more house, closed again; returns `root`."""
    raised_ledger(root, houses=("lighthouse", "why")).close()
    return root


def delete_ledger(root):
    from permission_ledger import ledger_path
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = ledger_path(root).with_name("permissions.db" + suffix)
        if p.exists():
            p.unlink()


def make_ledger_unreadable(root):
    from permission_ledger import ledger_path
    ledger_path(root).write_bytes(b"this is not a database " * 200)


def swap_in_another_ledger(root):
    from permission_ledger import Ledger
    delete_ledger(root)
    Ledger.create(root, "andy", now=T("2026-11-01")).close()


def _edit_ledger_meta(root, sql, args=()):
    import sqlite3
    from permission_ledger import ledger_path
    con = sqlite3.connect(ledger_path(root))
    con.execute(sql, args)
    con.commit()
    con.close()


def set_unknown_gate_value(root):
    _edit_ledger_meta(root, "UPDATE meta SET value='loud' WHERE key='gate'")


def delete_gate_key(root):
    _edit_ledger_meta(root, "DELETE FROM meta WHERE key='gate'")


def register_default_agent_at_home(led):
    """agent:default, acting for Andy's home and put in it."""
    do(led, ANDY, "register-agent", agent="agent:default", acts_for=HOME)
    do(led, ANDY, "put-agent", agent="agent:default", place=HOME)


def proposal_act(led, proposal_id) -> Act:
    """The Act a proposal's body holds."""
    import json
    body = json.loads(led.state().proposals[proposal_id].body)["act"]
    return Act(body["kind"], body["args"])


# ---------------------------------------------------------------- real stores and migration 029 (Task 16)

def house_dir(root, name):
    """`root/.engram/instances/<name>/`, made: `Storage` makes no directory."""
    from pathlib import Path
    path = Path(root) / ".engram" / "instances" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def insert_share(store, memory_id="a", content="x"):
    store.conn.execute(
        "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, reason, "
        "content_digest, shared_at) VALUES (?, ?, 'src', ?, 'home', 'aud', 'why', ?, '2026-11-01')",
        (f"s-{memory_id}", memory_id, memory_id, content))
    store.conn.commit()


def update_one_share(store):
    store.conn.execute("UPDATE shared_memories SET reason = 'changed' WHERE rowid = (SELECT min(rowid) FROM shared_memories)")
    store.conn.commit()


def delete_one_share(store):
    store.conn.execute("DELETE FROM shared_memories WHERE rowid = (SELECT min(rowid) FROM shared_memories)")
    store.conn.commit()


def house_before_029(root, name):
    """A real house built with a copy of migrations 001 to 028 only (SF4); closed, its path returned."""
    import shutil
    from pathlib import Path
    from storage import Storage
    src = Path(__file__).resolve().parent.parent / "migrations"
    dst = Path(root) / "m028"
    dst.mkdir(exist_ok=True)
    for f in sorted(src.glob("*.sql")):
        if int(f.name.split("_", 1)[0]) <= 28:
            shutil.copy(f, dst / f.name)
    path = house_dir(root, name) / "graph.db"
    Storage(str(path), migrations_dir=str(dst)).close()
    return path


def share_columns(path) -> set:
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(shared_memories)")}
    finally:
        con.close()


def counter_row(path):
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT count FROM shared_memories_changes WHERE id = 1").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------- the daemon's gate (Task 19; PF28: Tasks 20 and 21 reuse these)

OUTSIDE_HOME = "group:outside-home"
DAEMON_RECEIVER = "engram"


def _daemon_frame_kwargs(pub):
    from tests.test_lighthouse_daemon import CONTEXT
    return dict(receiver=DAEMON_RECEIVER, publisher=pub, context=CONTEXT, purpose="session-recall")


def recall(pub, query="shared: rivers need bridges"):
    from tests.test_lighthouse_daemon import NOW
    from lighthouse_protocol import recall_frame
    return recall_frame(**_daemon_frame_kwargs(pub), query=query, k=5, at=NOW)


def read(pub, memory_id):
    from lighthouse_protocol import read_frame
    return read_frame(**_daemon_frame_kwargs(pub), turn_id="turn-1", memory_ids=[memory_id])


def _daemon_over(root, publishers, busy_timeout_ms=None):
    import lighthouse_daemon
    from tests.test_lighthouse_daemon import FakeEmbeddings
    if busy_timeout_ms is not None:
        lighthouse_daemon.LEDGER_BUSY_MS = busy_timeout_ms     # conftest restores it after the test
    return lighthouse_daemon.PublisherDaemon(
        {p.name: p for p in publishers}, root / "s.sock", FakeEmbeddings(), engram_home=root)


def _outside_home_house(root, name, audiences):
    """A publisher whose only shared memory is an outside-home placement; the policy lists `audiences` for the
    receiver by hand. Returns (publisher, the memory's id)."""
    import uuid
    from storage import Storage
    from lighthouse_daemon import PublisherStore
    from tests.test_lighthouse_daemon import insert_share, unit, write_policy
    inst = house_dir(root, name)
    store = Storage(str(inst / "graph.db"))
    memory_id = str(uuid.uuid4())
    content = "outside home: rivers need bridges"
    store.add_episode(memory_id, "s", content, embedding=unit(content))
    insert_share(store, memory_id=memory_id, content=content, audience=OUTSIDE_HOME)
    store.close()
    write_policy(inst / "lighthouse-policy.json", audience_map={f"urn:{'engram'}:{DAEMON_RECEIVER}": audiences})
    return PublisherStore(name=name, db_path=inst / "graph.db", policy_path=inst / "lighthouse-policy.json",
                          disclosures_path=inst / "lighthouse-disclosures.db"), memory_id


def daemon_with_outside_home_placement(root, mode, hand_written_audiences, busy_timeout_ms=None):
    """A daemon over house `why` holding one outside-home placement. `mode` is `no-ledger`, `off` (a ledger whose gate
    was never raised), `shadow` or `enforce`. Returns (daemon, "why", the memory's id)."""
    from permission_ledger import Ledger
    pub, memory_id = _outside_home_house(root, "why", hand_written_audiences)
    if mode != "no-ledger":
        make_house(root, "lighthouse")
        led = Ledger.create(root, "andy", now=T("2026-11-01"))
        if mode != "off":
            raise_gate(led, mode)
        led.close()
    return _daemon_over(root, [pub], busy_timeout_ms), "why", memory_id


def raised_daemon(root, mode="enforce", busy_timeout_ms=None):
    """A daemon over house `why` (one commons placement, so a recall finds it) under a ledger raised to `mode`.
    Returns (daemon, "why")."""
    from tests.test_lighthouse_daemon import build_publisher
    pub = build_publisher(root, "why")
    make_house(root, "lighthouse")
    raised_ledger(root, houses=("lighthouse",), mode=mode).close()
    return _daemon_over(root, [pub], busy_timeout_ms), "why"


def add_publisher_house(daemon, root, name):
    """A copy of a house that ran 029 before the raise: a real store with the ledger's id taken out, added to the
    daemon's publishers."""
    import json
    import sqlite3
    from lighthouse_protocol import artifact_digest
    from tests.test_lighthouse_daemon import build_publisher
    pub = build_publisher(root, name)
    con = sqlite3.connect(pub.db_path)
    con.execute("DELETE FROM meta WHERE key='permissions_ledger_id'")
    con.commit()
    con.close()
    policy = json.loads(pub.policy_path.read_text())
    policy["issuer"] = f"urn:engram:{name}"
    policy.pop("digest")
    policy["digest"] = artifact_digest(policy)
    pub.policy_path.write_text(json.dumps(policy))
    daemon.publishers[name] = pub
    return name


def add_publisher_without_store(daemon, root, name):
    """A publisher named in the config whose `instances/<name>/` holds no `graph.db`."""
    import dataclasses
    from tests.test_lighthouse_daemon import build_publisher
    donor = build_publisher(root, "donor-" + name)
    inst = house_dir(root, name)
    pub = dataclasses.replace(donor, name=name, db_path=inst / "graph.db", policy_path=inst / "lighthouse-policy.json",
                              disclosures_path=inst / "lighthouse-disclosures.db")
    daemon.publishers[name] = pub
    return name


def make_real_house(root, name):
    """A house made now by Storage: migration 029 marks it with the raised ledger's id (Task 16)."""
    from storage import Storage
    house_dir(root, name)
    Storage(str(_house_path(root, name))).close()


def rerun_gate(root, mode):
    """`perform(Act("gate", ...))` again: it marks every house on disk."""
    from permission_ledger import Ledger
    led = Ledger.open(root)
    try:
        raise_gate(led, mode, now="2026-11-03")
    finally:
        led.close()


@contextlib.contextmanager
def hold_ledger_lock(root, kind):
    """Another connection to the ledger holding `BEGIN <kind>`, rolled back on exit."""
    import sqlite3
    from permission_ledger import ledger_path
    con = sqlite3.connect(ledger_path(root), isolation_level=None)
    con.execute(f"BEGIN {kind}")
    try:
        yield
    finally:
        con.execute("ROLLBACK")
        con.close()
