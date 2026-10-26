"""Test support for the permissions model: a World that writes table rows directly and checks nothing."""
import calendar
import hashlib
from datetime import datetime, timezone

import dataclasses

from permissions import Grant, Record, State, _row, _units, home_of, parse_selector, selector_json

SEED = 20261025
_OBJ = ("kinds", "stores", "layers", "lanes", "collections", "memories")


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
        tables = {t: [dict(r) for r in rs] for t, rs in self.rows.items()}
        return State.from_tables(tables, seq=self.seq, seq_at=self.seq_at, meta=self.meta, names=self.names)


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
