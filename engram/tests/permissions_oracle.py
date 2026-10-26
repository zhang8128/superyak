"""The brute-force oracle: a reading of P 5 and 6 over table rows, importing nothing from `permissions.py`.

It walks every record of every required layer for every needed (object, action), with no pre-filter and no
index. Tables are the JSON-ish rows of `State.to_tables()`; a use is a dict (see `use_json` in
permissions_support.py): requester, place, obj, copy, action, purpose, at, names, shows. A bulk use is
{"bulk": [use, ...]}: allowed when every per-object use is (P 6.4; the bound of 32 named memories is waived,
and the oracle does not apply it to anything else either).

Readings fixed where the spec leaves a choice (see the ledger's PF22 and Task 5's rulings):
- a membership row (collection, group, agent place) and a subject row are in force over
  [at(added_seq), at(removed_seq)); a removal later than the decision's seq does not exist yet;
- an allow counts a row when t is in that interval, a deny when the interval meets [anchor, t];
- a lane at instant tau is that of the last note with at <= tau (ties by seq); a pending note reads as every lane
  for a deny and as neither lane for an allow;
- a legacy layer is (name, actions it allows for the use); it is applied to every action of every need.
"""
import json

INF = float("inf")
ACTION_ORDER = ("recall", "read", "inject_context", "route", "imprint")
_CLOSURE = {"recall": ("recall",), "read": ("recall", "read"),
            "inject_context": ("recall", "read", "inject_context"), "route": ("route",),
            "imprint": ("recall", "read", "imprint")}
MAX_SUBJECTS = 8
MAX_NAMES = 32
MAX_COPY_LINKS = 4
MAX_GRANT_LINKS = 3
_STAR = "*"


def _doc(v):
    return json.loads(v) if isinstance(v, (str, bytes)) else v


def _parse_ref(ref):
    """(kind, instance_id, layer) of a mem:, road: or trail: ref, or None."""
    if not isinstance(ref, str) or ":" not in ref:
        return None
    head, _, rest = ref.partition(":")
    parts = rest.split("/")
    if head == "mem" and len(parts) == 3:
        return "memory", parts[0], parts[1]
    if head in ("road", "trail") and len(parts) == 2:
        return head, parts[0], None
    return None


def oracle_needs(use):
    """[(object, actions)]: the object first, then the memories a road or trail names, in ref order."""
    out = [(use["obj"], _CLOSURE[use["action"]])]
    parsed = _parse_ref(use["obj"])
    if parsed and parsed[0] in ("road", "trail"):
        shows = set(use.get("shows", ()))
        for m in sorted(set(use.get("names", ())) | shows):
            out.append((m, ("recall", "read", "inject_context") if m in shows else ("recall",)))
    return out


class _View:
    """The tables at one decision sequence number, with the rows that did not yet exist dropped."""

    def __init__(self, tables, seq_at, seq, person_members_only=False):
        self.seq_at = {int(k): v for k, v in seq_at.items()}
        self.seq = max(self.seq_at, default=0) if seq is None else seq
        self.person_members_only = person_members_only
        self.memo = {}

        def rows(name, added=None, undone=()):
            out = []
            for raw in tables.get(name, ()):
                r = dict(raw)
                if added is not None and r[added] > self.seq:
                    continue
                for col, clears in undone:
                    if r.get(col) is not None and r[col] > self.seq:
                        for c in clears:
                            r[c] = None
                out.append(r)
            return out

        rem = (("removed_seq", ("removed_seq",)),)
        self.persons = {r["id"]: r for r in rows("persons", "created_seq", (("retired_seq", ("retired_seq",)),))}
        self.places = {r["id"]: r for r in rows("places", "created_seq", (("retired_seq", ("retired_seq",)),))}
        self.parents = rows("place_parents", "added_seq")
        self.stewards = rows("place_stewards", "added_seq", rem)
        self.agents = {r["id"]: r for r in rows("agents", "created_seq", (("retired_seq", ("retired_seq",)),))}
        self.agent_places = rows("agent_places", "added_seq", rem)
        self.stores = {r["instance_id"]: r for r in rows("stores", "created_seq")}
        self.groups = {r["id"]: r for r in rows("groups", "created_seq")}
        self.group_members = rows("group_members", "added_seq", rem)
        self.members = rows("collection_members", "added_seq", rem)
        self.subjects = rows("subjects", "added_seq", rem)
        self.copies = {r["object"]: r["source"] for r in rows("copies")}
        self.notes = rows("lane_notes", "seq")
        rev = (("revoked_seq", ("revoked_seq",)),)
        self.records = {}
        for r in rows("records", "created_seq", rev):
            r["sel"] = _doc(r["selector"])
            self.records[r["id"]] = r
        self.grants = {}
        for r in rows("permission_grants", "created_seq", rev):
            r["opset"], r["env"] = set(_doc(r["ops"])), _doc(r["envelope"])
            self.grants[r["id"]] = r

    # -- time
    def at(self, seq):
        return self.seq_at[seq]

    def span(self, added, removed):
        return self.at(added), (INF if removed is None else self.at(removed))

    def in_force(self, row, t):
        a, b = self.span(row["added_seq"], row.get("removed_seq"))
        return a <= t < b

    def meets(self, row, lo, hi):
        a, b = self.span(row["added_seq"], row.get("removed_seq"))
        return a <= hi and b > lo and lo <= hi

    # -- places
    def anc(self, x):
        if ("anc", x) not in self.memo:
            out, todo = set(), [x]
            while todo:
                p = todo.pop()
                if p not in out:
                    out.add(p)
                    todo += [r["parent"] for r in self.parents if r["place"] == p]
            self.memo[("anc", x)] = frozenset(out)
        return self.memo[("anc", x)]

    def dom(self, x):
        if ("dom", x) not in self.memo:
            ps = [r["parent"] for r in self.parents if r["place"] == x]
            out = {x}
            if ps:
                out |= set.intersection(*(set(self.dom(p)) for p in ps))
            self.memo[("dom", x)] = frozenset(out)
        return self.memo[("dom", x)]

    def place_retired(self, x):
        return any(self.places.get(y, {}).get("retired_seq") is not None for y in self.anc(x))

    def act(self, agent):
        return self.agents[agent]["acts_for"] if agent in self.agents else None

    def agent_in(self, agent, t):
        return [r["place"] for r in self.agent_places if r["agent"] == agent and self.in_force(r, t)]

    # -- grants
    def grant_chain(self, gid):
        out, seen = [], set()
        while gid is not None and gid not in seen and gid in self.grants:
            seen.add(gid)
            out.append(self.grants[gid])
            gid = self.grants[gid]["parent_id"]
        return list(reversed(out))         # root first

    def grant_valid(self, gid, t):
        chain = self.grant_chain(gid)
        if not chain or chain[0]["parent_id"] is not None:
            return False
        if len(chain) > MAX_GRANT_LINKS:
            return False
        for g in chain:
            if g.get("revoked_seq") is not None or t >= g["expires"]:
                return False
        root = chain[0]
        return any(s["place"] == root["layer"] and s["person"] == root["issuer"] and s.get("removed_seq") is None
                   for s in self.stewards)

    # -- subjects
    def own_subjects(self, ref, t):
        out = set()
        parsed = _parse_ref(ref)
        if parsed:
            store = self.stores.get(parsed[1])
            if store is not None and store.get("imprint_of") is None:
                out.add(store["owner"])
        out |= {r["subject"] for r in self.subjects if r["object"] == ref and self.in_force(r, t)}
        return out

    def chain_subjects(self, ref, t):
        out, cur, seen = set(), ref, set()
        for _ in range(MAX_COPY_LINKS + 1):
            if cur is None or cur in seen:
                break
            seen.add(cur)
            out |= self.own_subjects(cur, t)
            cur = self.copies.get(cur)
        return out

    def subjects_of(self, obj, names, t):
        out = self.chain_subjects(obj, t)
        for m in names:
            out |= self.chain_subjects(m, t)
        return out

    # -- lanes
    def lane_at(self, notes, tau):
        last = None
        for n in notes:
            if n["at"] <= tau:
                last = n["lane"]
        return last

    def lane_ok(self, obj, lanes, anchor, t, deny):
        notes = sorted((n for n in self.notes if n["object"] == obj), key=lambda n: (n["at"], n["seq"]))
        if deny:
            if not notes:
                return True
            lo = anchor
            instants = [lo] + [n["at"] for n in notes if lo < n["at"] <= t] if lo <= t else []
            for tau in instants:
                lane = self.lane_at(notes, tau)
                if lane is not None and (lane in lanes or lane == "pending"):
                    return True
            return False
        if not notes:
            return False
        start = max(anchor, notes[0]["at"])
        if start > t:
            return False
        for tau in [start] + [n["at"] for n in notes if start < n["at"] <= t]:
            if self.lane_at(notes, tau) not in lanes:
                return False
        return True

    # -- selectors
    def audience_entry(self, v, layer, anchor, q, deny):
        a, P, _, t = q
        if v == "commons":
            return True
        act = self.act(a)
        if v == "self":
            return act == layer and (deny or layer in self.dom(P))
        if v.startswith("group:"):
            if deny:
                return any(r["group_id"] == v and r["agent"] == a and self.meets(r, anchor, t)
                           for r in self.group_members)
            g = self.groups.get(v)
            if g is None or not any(r["group_id"] == v and r["agent"] == a and self.in_force(r, t)
                                    for r in self.group_members):
                return False
            owner = self.persons.get(g["owner"])
            return owner is not None and owner["home"] in self.dom(P)
        if v.startswith("place:"):
            if not deny:
                return v in self.dom(P) and act is not None and v in self.dom(act)
            if v in self.anc(P) or (act is not None and v in self.anc(act)):
                return True
            return any(v in self.anc(r["place"]) for r in self.agent_places
                       if r["agent"] == a and self.meets(r, anchor, t))
        return False

    def collection_hit(self, obj, colls, layer, anchor, q, y, deny, assume):
        t = q[3]
        for i, r in enumerate(self.members):
            if r["object"] != obj or (colls != _STAR and r["collection"] not in colls):
                continue
            if deny:
                if self.meets(r, anchor, t):
                    return True
                continue
            if i in assume:
                return True
            if not self.in_force(r, t):
                continue
            if r["backing"] == "person":
                return True
            if self.person_members_only or not r["backing"].startswith("grant:"):
                continue
            gid = r["backing"][len("grant:"):]
            if self.grant_valid(gid, t) and all(
                    self.sel_match(g["env"], layer, anchor, q, obj, y, False, assume | {i})
                    for g in self.grant_chain(gid)):
                return True
        return False

    def sel_match(self, sel, layer, anchor, q, obj, y, deny, assume=frozenset()):
        a, P, p, t = q
        if not any(self.audience_entry(v, layer, anchor, q, deny) for v in sel["audience"]):
            return False
        if sel["requesters"] != _STAR and a not in sel["requesters"]:
            return False
        if sel["actions"] != _STAR and y not in sel["actions"]:
            return False
        if sel["purposes"] != _STAR and p not in sel["purposes"]:
            return False
        o = sel["objects"]
        parsed = _parse_ref(obj)
        kind, inst, lay = parsed if parsed else (None, None, None)
        if o["kinds"] != _STAR and kind not in o["kinds"]:
            return False
        if o["stores"] != _STAR and inst not in o["stores"]:
            return False
        if o["layers"] != _STAR and lay not in o["layers"]:
            return False
        if o["memories"] != _STAR and obj not in o["memories"]:
            return False
        if o["lanes"] != _STAR and not self.lane_ok(obj, o["lanes"], anchor, t, deny):
            return False
        if o["collections"] != _STAR and not self.collection_hit(obj, o["collections"], layer, anchor, q, y,
                                                                 deny, assume):
            return False
        return True

    # -- records
    def interval_ok(self, r, t):
        return r["valid_from"] <= t and (r["valid_until"] is None or t < r["valid_until"])

    def matches(self, r, q, obj, y, ignore_revoked=False):
        t = q[3]
        if r.get("revoked_seq") is not None and not ignore_revoked:
            return False
        if not self.interval_ok(r, t):
            return False
        deny = r["effect"] == "deny"
        if not self.sel_match(r["sel"], r["layer"], r["anchor"], q, obj, y, deny):
            return False
        cur, seen = r, {r["id"]}
        while cur.get("replaces") is not None:       # the chain: revocations ignored, intervals read
            cur = self.records.get(cur["replaces"])
            if cur is None or cur["id"] in seen:
                break
            seen.add(cur["id"])
            if not self.interval_ok(cur, t) or not self.sel_match(
                    cur["sel"], cur["layer"], cur["anchor"], q, obj, y, cur["effect"] == "deny"):
                return False
        if r["backing"].startswith("grant:"):
            gid = r["backing"][len("grant:"):]
            if not self.grant_valid(gid, t):
                return False
            if not all(self.sel_match(g["env"], r["layer"], r["anchor"], q, obj, y, deny)
                       for g in self.grant_chain(gid)):
                return False
        return True

    def layer_allows(self, layer, q, obj, y):
        restriction = layer.startswith("agent:")
        if not restriction and layer not in self.places:
            return False
        recs = [r for r in self.records.values() if r["layer"] == layer]
        if any(self.matches(r, q, obj, y) for r in recs if r["effect"] == "deny"):
            return False
        if restriction:
            return True
        return any(self.matches(r, q, obj, y) for r in recs if r["effect"] == "allow")

    def subject_layer(self, s):
        if s.startswith("person:"):
            p = self.persons.get(s)
            return p["home"] if p else "place:home/" + s[len("person:"):]
        return s

    def subject_retired(self, s):
        p = self.persons.get(s)
        return p is not None and (p.get("retired_seq") is not None or self.place_retired(p["home"]))

    def holding_place(self, copy):
        head, _, rest = copy.partition(":")
        if head == "store":
            key = rest
        elif head == "imprint" and rest.count("/") == 1:
            key = rest.split("/")[1]
        else:
            return None
        s = self.stores.get(key)
        return s["place"] if s else None

    def allowed(self, u, legacy):
        a, P, t = u["requester"], u["place"], u["at"]
        q = (a, P, u["purpose"], t)
        if a not in self.agents or self.agents[a].get("retired_seq") is not None or P not in self.agent_in(a, t):
            return False
        H = self.holding_place(u["copy"])
        if self.place_retired(P) or (H is not None and self.place_retired(H)):
            return False
        for obj, actions in oracle_needs(u):
            names = u.get("names", ()) if obj == u["obj"] else ()
            subs = self.subjects_of(obj, names, t)
            if not subs or len(subs) > MAX_SUBJECTS or any(self.subject_retired(s) for s in subs):
                return False
            if obj == u["obj"] and len(names) > MAX_NAMES:
                return False
            layers = {self.subject_layer(s) for s in subs} | set(self.anc(P))
            if H is None:
                return False
            layers |= set(self.anc(H))
            for y in actions:
                if any(y not in allowed for _, allowed in legacy):
                    return False
                if not self.layer_allows(a, q, obj, y):          # the requester's own restriction layer
                    return False
                if not all(self.layer_allows(L, q, obj, y) for L in layers):
                    return False
        return True


def _view(tables, seq_at, seq, person_members_only=False):
    key = (id(tables), id(seq_at), seq, person_members_only)
    hit = _CACHE.get(key)
    if hit is None or hit[0] is not tables or hit[1] is not seq_at:
        if len(_CACHE) > 64:
            _CACHE.clear()
        hit = _CACHE[key] = (tables, seq_at, _View(tables, seq_at, seq, person_members_only))
    return hit[2]


_CACHE: dict = {}


def _q(u):
    return (u["requester"], u["place"], u["purpose"], u["at"])


def oracle_allowed(tables, seq_at, use, legacy=(), *, seq=None) -> bool:
    """Is the use allowed at the state of `tables` (as of `seq`, default the last)?"""
    v = _view(tables, seq_at, seq)
    if "bulk" in use:
        return all(v.allowed(x, legacy) for x in use["bulk"])
    return v.allowed(use, legacy)


def oracle_layer_allows(tables, seq_at, use, layer, action, *, obj=None, seq=None) -> bool:
    """Does `layer` allow `action` on `obj` (default the use's object) for the use's requester, place, purpose
    and time? A consent layer that does not exist allows nothing."""
    return _view(tables, seq_at, seq).layer_allows(layer, _q(use), obj or use["obj"], action)


def oracle_record_matches(tables, seq_at, record_id, use, action, *, obj=None, seq=None, ignore_revoked=False,
                          person_members_only=False) -> bool:
    v = _view(tables, seq_at, seq, person_members_only)
    r = v.records.get(record_id)
    return r is not None and v.matches(r, _q(use), obj or use["obj"], action, ignore_revoked)


def _home(v, person):
    return v.persons[person]["home"]


def oracle_sig_plus(tables, seq_at, use, action, person, *, obj=None, seq=None) -> bool:
    """Sig+ (L4): some allow `person` wrote, person-backed, in their home layer, matches; collections are read
    through person-backed memberships only. A revoked or replaced original still counts: it was signed."""
    v = _view(tables, seq_at, seq, True)
    home = _home(v, person)
    return any(r["layer"] == home and r["effect"] == "allow" and r["set_by"] == person and r["backing"] == "person"
               and v.matches(r, _q(use), obj or use["obj"], action, ignore_revoked=True)
               for r in v.records.values())


def oracle_sig_minus(tables, seq_at, use, action, person, *, obj=None, seq=None) -> bool:
    """Sig- (L4): some deny `person` wrote, as they last left it (unrevoked), in their home layer, matches."""
    v = _view(tables, seq_at, seq)
    home = _home(v, person)
    return any(r["layer"] == home and r["effect"] == "deny" and r["set_by"] == person
               and v.matches(r, _q(use), obj or use["obj"], action) for r in v.records.values())


def oracle_env(tables, seq_at, use, action, person, *, anchor, obj=None, seq=None) -> bool:
    """Env (L4) at the use's time: the use lies in the envelope of one of `person`'s valid root grants."""
    v = _view(tables, seq_at, seq)
    home, q = _home(v, person), _q(use)
    return any(g["parent_id"] is None and g["issuer"] == person and g["layer"] == home
               and v.grant_valid(g["id"], q[3])
               and v.sel_match(g["env"], home, anchor, q, obj or use["obj"], action, False)
               for g in v.grants.values())
