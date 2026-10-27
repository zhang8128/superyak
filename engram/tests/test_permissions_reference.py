"""Task P0: every field of every decision stays equal to the frozen reference of a083a96 (P 6.5, 17 F1).

tests/permissions_reference.py is a copy of a083a96's decision code, never edited again. For random worlds, the F1
fixtures and bulk uses under small bounds, `decide`, `decide_bulk` (named and counted, grouped and not) and
`eligible_set` must give the reference's `to_json()`, versions, `processed` and `failed_need`, or the same refusal
error, on a whole State and on a lazy State written to a ledger by SQL."""
import dataclasses
import hashlib
import json
import random
import shutil

import pytest

import permissions
import tests.permissions_reference as ref
from permissions import (BulkUse, LegacyLayer, Placement, RuleError, _COLUMNS, decide, decide_bulk, eligible_set,
                         selector_json)
from tests.permissions_support import Bulk, T, derived_trails, generated_world, random_world, sample_uses, touches
from tests.permissions_support import AGENT, COPY, PLACE
from tests.test_permissions_f1 import FIXTURES, load_state, run_case

CASES = 40
USES = 30


def legacy_for(seed):
    def allows(use, action, seed=seed):
        return hashlib.sha256(f"{seed}|{use.obj}|{action}".encode()).digest()[0] % 7 != 0
    return (LegacyLayer("publisher", allows), LegacyLayer("receiver", lambda u, x: True))


def fields(d):
    """Every field of a decision that a caller can see."""
    if isinstance(d, Exception):
        return {"error": f"{type(d).__name__}: {d}"}
    return {"d": d.to_json(), "versions": dict(sorted(d.versions.items())), "processed": d.processed,
            "failed": d.failed_need}


def guard(fn):
    try:
        return fn()
    except RuleError as e:
        return e


def same(label, live, old):
    a, b = fields(live), fields(old)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), label


M2_CHANGED = []          # the eligible sets whose horizon the final review's M2 moved earlier, by label


def m2_terms(s, placements, requester, t):
    """The final review's M2, read from the State apart from the code under test: every time after t at which a
    row an eligible set reads by its log time comes into or goes out of force. The requester's places and group
    memberships; each placed object's memberships, subject rows (up its `copies` chain) and lane notes; and the
    re-review's term, the anchor of every unrevoked record whose anchor is after t."""
    def later(added, removed):
        lo = s.seq_at[added]
        hi = None if removed is None or removed > s.seq else s.seq_at[removed]
        return [x for x in (lo, hi) if x is not None and x > t]
    out = []
    for r in s.agent_places.get(requester, ()):
        out += later(r.added_seq, r.removed_seq)
    for rows in s.group_members.values():
        out += [x for r in rows if r.agent == requester for x in later(r.added_seq, r.removed_seq)]
    for o in {p.obj for p in placements if p.obj is not None}:
        out += [x for m in s.member_of.get(o, ()) for x in later(m.added_seq, m.removed_seq)]
        cur, seen = o, set()
        for _ in range(permissions.MAX_COPY_CHAIN + 1):
            if cur is None or cur in seen:
                break
            seen.add(cur)
            out += [x for r in s.subjects.get(cur, ()) for x in later(r.added_seq, r.removed_seq)]
            cur = s.copies.get(cur)
        out += [n.at for n in s.lane_notes.get(o, ()) if n.at > t]
    out += [r.anchor for r in s.records.values()
            if r.anchor > t and (r.revoked_seq is None or r.revoked_seq > s.seq)]
    return out


def same_set(label, live, old, m2=()):
    """Equal eligible sets, except that M2 (the final review) may move the horizon earlier: to the earliest of the
    reference's horizon and `m2`, the times `m2_terms` reads."""
    if isinstance(live, Exception) or isinstance(old, Exception):
        assert fields(live) == fields(old), label
        return
    terms = list(m2) + ([] if old.horizon is None else [old.horizon])
    expected = min(terms) if terms else None
    if expected != old.horizon:
        M2_CHANGED.append(label)
    assert (sorted(live.memory_ids), live.horizon) == (sorted(old.memory_ids), expected), label
    assert sorted(live.decisions) == sorted(old.decisions), label
    for k in sorted(live.decisions):
        same(f"{label}/{k}", live.decisions[k], old.decisions[k])


def lazy_state(w, home):
    """The World's tables written into a ledger under `home` by SQL, then read back as a lazy State."""
    from lighthouse_protocol import canonical_json
    from permission_ledger import ZERO, Ledger, _digest
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    led = Ledger._blank(home, "reference-ledger")
    conn = led.conn
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO meta VALUES(?,?)", [("owner", w.owner), ("admins", w.owner)])
    for table, cols in _COLUMNS.items():
        def cell(c, r, table=table):
            v = r.get(c)
            if table == "records" and c == "selector":
                return selector_json(v)
            if table == "permission_grants" and c in ("ops", "envelope") and not isinstance(v, str):
                return canonical_json(v)
            return v
        conn.executemany(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                         ([cell(c, r) for c in cols] for r in w.rows.get(table, [])))
    prev = ZERO
    for seq in range(1, w.seq + 1):
        entry = {"seq": seq, "at": w.seq_at[seq], "kind": "filler", "ref": "none", "actor": w.owner,
                 "channel": "terminal", "under_grant": None, "proposal_id": None, "body": "{}"}
        dg = _digest(prev, entry)
        conn.execute("INSERT INTO ledger_log VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (seq, entry["at"], "filler", "none", w.owner, "terminal", None, None, "{}", prev, dg))
        prev = dg
    conn.execute("COMMIT")
    led.close()
    led = Ledger.open_read_only(home)
    s = led.state()
    led.close()
    return s


def check_world(tag, w, s, rng, n_uses, when=None):
    """With `when`, each sampled use (a bulk use's every part) is moved to the time `when()` draws."""
    roads = getattr(w.cfg, "roads", {}) if w.cfg else {}
    for i, u in enumerate(sample_uses(rng, w, n_uses)):
        if when is not None:
            at = when()
            u = (Bulk(tuple(dataclasses.replace(x, at=at) for x in u.uses)) if isinstance(u, Bulk)
                 else dataclasses.replace(u, at=at))
        leg = legacy_for(f"{tag}-{i}")
        if isinstance(u, Bulk):
            first = u.uses[0]
            objs = tuple(x.obj for x in u.uses)
            for named in (True, False):
                b = BulkUse(requester=first.requester, place=first.place, objects=objs, copy=first.copy,
                            action=first.action, purpose=first.purpose, at=first.at, named=named,
                            names=lambda o: roads.get(o, ()))
                for group in (True, False):
                    same(f"{tag}/{i}/bulk/{named}/{group}", guard(lambda: decide_bulk(s, b, group=group)),
                         guard(lambda: ref.decide_bulk(s, b, group=group)))
                same(f"{tag}/{i}/bulk-legacy/{named}", guard(lambda: decide_bulk(s, b, legacy=leg)),
                     guard(lambda: ref.decide_bulk(s, b, legacy=leg)))
            for j, x in enumerate(u.uses):
                same(f"{tag}/{i}/sub/{j}", guard(lambda: decide(s, x)), guard(lambda: ref.decide(s, x)))
            continue
        same(f"{tag}/{i}", guard(lambda: decide(s, u)), guard(lambda: ref.decide(s, u)))
        same(f"{tag}/{i}/legacy", guard(lambda: decide(s, u, legacy=leg)), guard(lambda: ref.decide(s, u, legacy=leg)))
        objs = list(getattr(w.cfg, "objects", [])) + [None]
        placements = [Placement(f"id{k}", o, u.copy) for k, o in enumerate(objs)]
        placements += [Placement(f"dup{k}", o, u.copy) for k, o in enumerate(objs[:3])]
        kw = dict(requester=u.requester, place=u.place, purpose=u.purpose, action=u.action, at=u.at)
        same_set(f"{tag}/{i}/es", guard(lambda: eligible_set(s, placements, **kw)),
                 guard(lambda: ref.eligible_set(s, placements, **kw)),
                 m2=m2_terms(s, placements, u.requester, u.at))
        for k, o in enumerate(objs[:-1]):
            x = dataclasses.replace(u, obj=o, names=roads.get(o, ()), shows=frozenset())
            same(f"{tag}/{i}/each/{k}", guard(lambda: decide(s, x)), guard(lambda: ref.decide(s, x)))


@pytest.mark.parametrize("case", range(CASES))
def test_random_world_decisions_equal_the_reference(case, tmp_path):
    w = random_world(random.Random(f"perf-diff-{case}"))
    check_world(f"rw{case}", w, w.state(), random.Random(f"perf-diff-uses-{case}"), USES)
    if case % 6 == 0:
        check_world(f"rw{case}-lazy", w, lazy_state(w, tmp_path / "ledger"),
                    random.Random(f"perf-diff-uses-{case}"), USES // 2)


@pytest.mark.parametrize("case", range(CASES))
def test_uses_drawn_before_a_records_anchor_equal_the_reference(case, tmp_path):
    """The re-review's M2: a random world draws no use before every record exists (its `t0`), so no record's anchor
    is ever after t there. These uses are drawn before t0, from a day before the first anchor, or a second either
    side of an anchor: every decision must still equal the reference, and an eligible set's horizon may move only
    to `m2_terms`, whose last term is then the earliest anchor after t."""
    w = random_world(random.Random(f"perf-diff-{case}"))
    s = w.state()
    anchors = sorted({r.anchor for r in s.records.values()})
    rng = random.Random(f"perf-diff-before-{case}")

    def when():
        if rng.random() < 0.5:
            return rng.randint(anchors[0] - 86_400, w.cfg.t0 - 1)
        return rng.choice(anchors) + rng.choice([-1, 0, 1])
    check_world(f"rw{case}-before", w, s, random.Random(f"perf-diff-uses-{case}"), USES // 2, when)
    if case % 6 == 0:
        check_world(f"rw{case}-before-lazy", w, lazy_state(w, tmp_path / "ledger"),
                    random.Random(f"perf-diff-uses-{case}"), USES // 2, when)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_f1_decisions_equal_the_reference(path, monkeypatch):
    doc = json.loads(path.read_text())
    st = load_state(doc)
    for n, case in enumerate(doc["cases"]):
        live = guard(lambda: run_case(st, case))
        monkeypatch.setattr("tests.test_permissions_f1.decide", ref.decide)
        monkeypatch.setattr("tests.test_permissions_f1.decide_bulk", ref.decide_bulk)
        old = guard(lambda: run_case(st, case))
        monkeypatch.undo()
        same(f"{path.stem}/{n}", live, old)


@pytest.fixture(scope="module")
def trails_world():
    return generated_world(placements=0, layers=43, records_per_layer=256, universe=800, trails=12)[0]


@pytest.mark.parametrize("cap", [3, 50])
def test_bulk_bound_equals_the_reference(cap, trails_world, monkeypatch):
    monkeypatch.setattr(permissions, "MAX_BULK_MEMORIES", cap)
    for group in (True, False):
        b = BulkUse(requester=AGENT, place=PLACE, objects=derived_trails(12), copy=COPY, action="imprint",
                    purpose="trail-evaluation", at=T("2026-11-02"), named=False,
                    names=lambda t: touches(t, 8, universe=800))
        same(f"gen/{cap}/{group}", guard(lambda: decide_bulk(trails_world, b, group=group)),
             guard(lambda: ref.decide_bulk(trails_world, b, group=group)))
    for case in range(0, CASES, 3):
        w = random_world(random.Random(f"perf-diff-{case}"))
        st, roads = w.state(), getattr(w.cfg, "roads", {})
        for i, u in enumerate(sample_uses(random.Random(f"tight-{case}"), w, 25)):
            if not isinstance(u, Bulk):
                continue
            first = u.uses[0]
            bb = BulkUse(requester=first.requester, place=first.place,
                         objects=tuple(x.obj for x in u.uses) + tuple(roads), copy=first.copy, action=first.action,
                         purpose=first.purpose, at=first.at, named=False, names=lambda o: roads.get(o, ()))
            same(f"rw{case}/{i}/{cap}", guard(lambda: decide_bulk(st, bb, group=False)),
                 guard(lambda: ref.decide_bulk(st, bb, group=False)))


def test_the_comparison_notices_one_changed_cited_id():
    """Step 1(c): mutate one cited id in a copy of a decision; `same` must fail."""
    doc = json.loads(FIXTURES[0].read_text())
    st = load_state(doc)
    d = next(x for x in (guard(lambda: run_case(st, c)) for c in doc["cases"])
             if not isinstance(x, Exception) and x.cited and x.cited[0].records)
    same("unmutated", d, d)

    class Mutated:
        versions, processed, failed_need = d.versions, d.processed, d.failed_need

        @staticmethod
        def to_json():
            j = json.loads(json.dumps(d.to_json()))
            j["cited"][0]["records"][0] += "-mutated"
            return j
    with pytest.raises(AssertionError):
        same("mutated", Mutated, d)
