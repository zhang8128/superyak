"""Test support for the permissions model: a World that writes table rows directly and checks nothing."""
import calendar
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import copy as _copy
import dataclasses
from typing import NamedTuple

from permissions import (ACTIONS, GRANT_OPS, BulkUse, Grant, Record, State, Use, _row, _units, home_of,
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
    """PF29: [(name, the actions the layer's callable allows for u)]; a callable can't be serialised without u."""
    return [(layer.name, frozenset(a for a in ACTIONS if layer.allows(u, a))) for layer in legacy]


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
