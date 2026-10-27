"""A State reads per-object rows through a bounded cache (SH-2; P 5.6, 15)."""
import gc
import random
import sqlite3
import threading
import tracemalloc
from dataclasses import replace

import pytest

import permissions
from lighthouse_protocol import canonical_json
from permission_ledger import Ledger
from permissions import _COLUMNS, _NULLABLE, BulkUse, Placement, State, decide, decide_bulk, eligible_set
from tests.permissions_memory_support import HOME, OWNER, synthetic_ledger
from tests.permissions_support import Bulk, T, random_world, sample_uses

MB = 1 << 20
RIO = "agent:rio-grande"
AT = 2_000_000


def _traced(fn):
    gc.collect()
    tracemalloc.start()
    try:
        out = fn()
        gc.collect()
        return out, tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()


def _with_agent(home):
    from permission_ledger import ledger_path
    conn = sqlite3.connect(ledger_path(home), isolation_level=None)
    try:
        conn.execute("INSERT INTO agents VALUES(?,?,1,NULL)", (RIO, HOME))
        conn.execute("INSERT INTO stores VALUES('house','engram',?,?,NULL,1)", (OWNER, HOME))
        conn.execute("INSERT INTO agent_places VALUES(?,?,1,NULL)", (RIO, HOME))
    finally:
        conn.close()


def _mems(n):
    return tuple(f"mem:S/episode/m{i}" for i in range(n))


def _bulk(objects):
    return BulkUse(requester=RIO, place=HOME, objects=tuple(objects), copy="store:house", action="recall",
                   purpose="care-coordination", at=AT, named=False)


# ---------------------------------------------------------------- memory

def test_state_loads_no_per_object_rows_up_front(tmp_path):
    synthetic_ledger(tmp_path, 20_000)
    led = Ledger.open_read_only(tmp_path)
    try:
        state, (current, _) = _traced(led.state)
        assert current < 12 * MB, f"the State holds {current / MB:.1f} MB"
        assert len(state.subjects) == 20_000 and len(state.lane_notes) == 20_000
    finally:
        led.close()


def test_a_states_rows_stay_bounded(tmp_path):
    synthetic_ledger(tmp_path, 20_000, records=True)
    _with_agent(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        def run():
            state = led.state()
            d = decide_bulk(state, _bulk(_mems(20_000)))
            assert d.allowed, d.refusal
            del d
            return state
        state, (current, _) = _traced(run)
        assert current < 40 * MB, f"the State holds {current / MB:.1f} MB"
        assert state._loader.cached_rows() <= permissions.STATE_ROWS
    finally:
        led.close()


def test_one_collection_larger_than_the_cache_is_read_and_not_kept(tmp_path):
    synthetic_ledger(tmp_path, 100_000, per_object_rows=False)
    led = Ledger.open_read_only(tmp_path)
    try:
        state = led.state()
        rows = state.collection_members["collection:andy/memories"]
        assert len(rows) == 100_000 and rows[0].object == "mem:S/episode/m0"
        assert state._loader.cached_rows() == 0
        assert len(state.collection_members) == 1
    finally:
        led.close()


def test_the_cache_keeps_at_most_the_bound_and_pools_strings(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "STATE_ROWS", 30)
    synthetic_ledger(tmp_path, 40)
    led = Ledger.open_read_only(tmp_path)
    try:
        state = led.state()
        for ref in _mems(40):
            assert len(state.subjects[ref]) == 7
            assert state._loader.cached_rows() <= 30
        a, b = state.subjects[_mems(40)[0]][0], state.subjects[_mems(40)[1]][0]
        assert a.subject is b.subject and a.added_by is b.added_by
    finally:
        led.close()


def test_prefetch_is_called_per_chunk_of_512(tmp_path, monkeypatch):
    synthetic_ledger(tmp_path, 1300, records=True)
    _with_agent(tmp_path)
    calls = []
    real = State.prefetch
    monkeypatch.setattr(State, "prefetch", lambda self, refs: (calls.append(len(list(refs))), real(self, refs))[1])
    led = Ledger.open_read_only(tmp_path)
    try:
        state = led.state()
        assert decide_bulk(state, _bulk(_mems(1300))).allowed
        assert calls == [512, 512, 276]
        calls.clear()
        placements = [Placement(f"m{i}", f"mem:S/episode/m{i}", "store:house") for i in range(1300)]
        got = eligible_set(state, placements, requester=RIO, place=HOME, purpose="care-coordination",
                           action="recall", at=AT)
        assert len(got.memory_ids) == 1300 and calls == [512, 512, 276]
    finally:
        led.close()


def test_an_eager_state_prefetch_is_a_no_op():
    s = State.from_tables({}, seq=0, seq_at={}, meta={})
    assert s.prefetch(["mem:S/episode/m1"]) is None and s.self_claims == ()


# ---------------------------------------------------------------- the world in a ledger file

def _write_world(home, w) -> Ledger:
    led = Ledger._blank(home, "world-ledger")
    conn = led.conn
    conn.execute("BEGIN")
    for k, v in w.meta.items():
        conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))
    for table, rows in w.rows.items():
        cols = _COLUMNS[table]
        for r in rows:
            vals = []
            for c in cols:
                v = r[c] if c in r else (None if c in _NULLABLE else r[c])
                if table == "places" and c == "pseudonym_salt" and isinstance(v, str):
                    v = bytes.fromhex(v)
                elif table == "records" and c == "selector" and not isinstance(v, (dict, str)):
                    v = permissions.selector_json(v)
                if isinstance(v, (dict, list)):
                    v = canonical_json(v)
                vals.append(v)
            conn.execute(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", vals)
    named = {}
    for p in w.rows.get("places", ()):
        if p["id"] in w.names:
            s = p["created_seq"]
            while s in named:
                s += 1
            named[s] = p["id"]
    pad = "0" * 64
    for s in range(1, w.seq + 1):
        if s in named:
            kind, ref, body = "register-place", named[s], canonical_json({"name": w.names[named[s]]})
        else:
            kind, ref, body = "collect", "x", "{}"
        conn.execute("INSERT INTO ledger_log VALUES(?,?,?,?,?,?,NULL,NULL,?,?,?)",
                     (s, w.seq_at[s], kind, ref, w.owner, "terminal", body, pad, pad))
    conn.execute("COMMIT")
    return led


def _flat(u):
    return u.uses if isinstance(u, Bulk) else (u,)


def test_lazy_and_eager_states_decide_alike(tmp_path):
    checked = 0
    for case in range(50):
        rng = random.Random(f"sh2-lazy-{case}")
        w = random_world(rng)
        led = _write_world(tmp_path / f"c{case}", w)
        try:
            uses = [x for u in sample_uses(rng, w, 8) for x in _flat(u)]
            for seq in (w.seq, w.seq // 2):
                eager, lazy = w.state_at(seq), led.state(seq)
                assert lazy.names == eager.names
                for x in uses:
                    assert decide(lazy, x) == decide(eager, x), (case, seq, x)
                    checked += 1
        finally:
            led.close()
    assert checked > 300


# ---------------------------------------------------------------- reading at a seq

def _ins(led, table, row, at, kind="test"):
    return led._append(kind, "x", OWNER, "terminal", {"insert": [{"table": table, "row": row}]}, at=at)


def _upd(led, table, where, sets, at):
    return led._append("test", "x", OWNER, "terminal",
                       {"update": [{"table": table, "where": where, "set": sets}]}, at=at)


def _fresh(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    return led


OBJ, COLL = "mem:S/episode/m1", "collection:andy/c"


def test_rows_at_an_earlier_seq_read_as_they_were(tmp_path):
    led = _fresh(tmp_path)
    try:
        _ins(led, "collections", {"id": COLL, "owner": OWNER, "created_seq": "@seq"}, T("2026-11-01"))
        pre = led.seq()
        a = _ins(led, "subjects", {"object": OBJ, "subject": "person:amy", "added_seq": "@seq", "added_by": OWNER,
                                   "self_claimed": 0}, T("2026-11-02"))
        _ins(led, "collection_members", {"collection": COLL, "object": OBJ, "backing": "person",
                                         "added_seq": "@seq", "added_by": OWNER}, T("2026-11-02"))
        _ins(led, "lane_notes", {"object": OBJ, "lane": "personal", "at": T("2026-11-02"), "seq": "@seq"},
             T("2026-11-02"))
        _ins(led, "copies", {"object": "mem:Z/episode/c1", "source": OBJ, "added_seq": "@seq"}, T("2026-11-02"))
        last_add = led.seq()
        b = _upd(led, "subjects", {"object": OBJ, "subject": "person:amy"},
                 {"removed_seq": "@seq", "removed_by": OWNER}, T("2026-11-03"))
        b2 = _upd(led, "collection_members", {"collection": COLL, "object": OBJ},
                  {"removed_seq": "@seq", "removed_by": OWNER}, T("2026-11-03"))
        end = led.seq()
        before = led.state(pre)
        for m in (before.subjects, before.member_of, before.collection_members, before.lane_notes, before.copies,
                  before.copy_seqs):
            assert len(m) == 0
        assert before.subjects.get(OBJ) is None and OBJ not in before.subjects
        assert before.collection_members.get(COLL, ()) == () and before.copies.get("mem:Z/episode/c1") is None
        assert list(before.subjects.items()) == []
        live = led.state(last_add)
        (row,) = live.subjects[OBJ]
        assert (row.added_seq, row.removed_seq, row.removed_by) == (a, None, None)
        assert live.member_of[OBJ][0].removed_seq is None and live.collection_members[COLL][0].removed_seq is None
        assert [n.lane for n in live.lane_notes[OBJ]] == ["personal"]
        assert live.copies["mem:Z/episode/c1"] == OBJ and live.copy_seqs["mem:Z/episode/c1"] == last_add
        gone = led.state(end)
        (row,) = gone.subjects[OBJ]
        assert (row.removed_seq, row.removed_by) == (b, OWNER)
        assert gone.member_of[OBJ][0].removed_seq == b2 and gone.collection_members[COLL][0].removed_seq == b2
        assert len(gone.subjects) == 1 and dict(gone.subjects.items()) == {OBJ: gone.subjects[OBJ]}
        assert led.state(b - 1).subjects[OBJ][0].removed_seq is None
    finally:
        led.close()


def test_a_state_asked_after_later_writes_decides_at_its_seq(tmp_path):
    led = _fresh(tmp_path)
    try:
        t = T("2026-11-01")
        _ins(led, "stores", {"instance_id": "S", "name": "S", "owner": OWNER, "place": HOME, "created_seq": "@seq"}, t)
        _ins(led, "agents", {"id": RIO, "acts_for": OWNER, "created_seq": "@seq"}, t)
        _ins(led, "agent_places", {"agent": RIO, "place": HOME, "added_seq": "@seq"}, t)
        _ins(led, "collections", {"id": COLL, "owner": OWNER, "created_seq": "@seq"}, t)
        sel = {"audience": ["self"], "requesters": "*", "actions": ["recall"], "purposes": "*",
               "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": "*",
                           "memories": "*"}}
        _ins(led, "records", {"id": "r1", "layer": HOME, "effect": "allow", "selector": sel, "valid_from": t,
                              "anchor": t, "backing": "person", "set_by": OWNER, "channel": "terminal",
                              "reason": "t", "created": t, "created_seq": "@seq"}, t)
        _ins(led, "subjects", {"object": "mem:S/episode/m1", "subject": "person:amy", "added_seq": "@seq",
                               "added_by": OWNER, "self_claimed": 0}, t)
        _ins(led, "subjects", {"object": "mem:S/episode/m2", "subject": "person:amy", "added_seq": "@seq",
                               "added_by": OWNER, "self_claimed": 0}, t)
        _ins(led, "lane_notes", {"object": "mem:S/episode/m1", "lane": "personal", "at": t, "seq": "@seq"}, t)
        old = led.seq()
        cold, warm = led.state(), led.state()
        objs = ["mem:S/episode/m1", "mem:S/episode/m2", "mem:S/episode/m3", "mem:Z/episode/c1"]
        uses = [permissions.Use(requester=RIO, place=HOME, obj=o, copy="store:house", action=a,
                                purpose="care-coordination", at=t + 86400 * d)
                for o in objs for a in ("recall", "route") for d in (0, 5)]
        for u in uses:
            decide(warm, u)
        # later writes: subjects and memberships come and go, notes arrive, a copy is recorded
        t2 = T("2026-11-03")
        _upd(led, "subjects", {"object": "mem:S/episode/m1", "subject": "person:amy"},
             {"removed_seq": "@seq", "removed_by": OWNER}, t2)
        _ins(led, "subjects", {"object": "mem:S/episode/m3", "subject": "person:bo", "added_seq": "@seq",
                               "added_by": OWNER, "self_claimed": 1}, t2)
        _ins(led, "collection_members", {"collection": COLL, "object": "mem:S/episode/m1", "backing": "person",
                                         "added_seq": "@seq", "added_by": OWNER}, t2)
        _upd(led, "collection_members", {"collection": COLL, "object": "mem:S/episode/m1"},
             {"removed_seq": "@seq", "removed_by": OWNER}, t2)
        _ins(led, "lane_notes", {"object": "mem:S/episode/m2", "lane": "work", "at": t2, "seq": "@seq"}, t2)
        _ins(led, "lane_notes", {"object": "mem:S/episode/m1", "lane": "work", "at": t2, "seq": "@seq"}, t2)
        _ins(led, "copies", {"object": "mem:Z/episode/c1", "source": "mem:S/episode/m2", "added_seq": "@seq"}, t2)
        eager = State.from_tables({k: v for k, v in led.tables().items() if k in _COLUMNS}, seq=old, seq_at=dict(cold.seq_at), meta=cold.meta, names=cold.names)
        assert cold.seq == old
        for u in uses:
            want = decide(eager, u)
            assert decide(cold, u) == want and decide(warm, u) == want, u
        assert eager.subjects == dict(cold.subjects.items())
        assert cold.self_claims == ()
    finally:
        led.close()


# ---------------------------------------------------------------- walks become queries

def test_self_claims_and_pending_lane_notes_are_queries(tmp_path):
    led = _fresh(tmp_path)
    try:
        t = T("2026-11-01")
        _ins(led, "subjects", {"object": "mem:S/episode/m1", "subject": "person:amy", "added_seq": "@seq",
                               "added_by": "person:amy", "self_claimed": 1}, t)
        _ins(led, "subjects", {"object": "mem:S/episode/m2", "subject": "person:bo", "added_seq": "@seq",
                               "added_by": OWNER, "self_claimed": 0}, t)
        _ins(led, "subjects", {"object": "mem:S/episode/m3", "subject": "person:cy", "added_seq": "@seq",
                               "added_by": "person:cy", "self_claimed": 1}, t)
        _upd(led, "subjects", {"object": "mem:S/episode/m3", "subject": "person:cy"},
             {"removed_seq": "@seq", "removed_by": OWNER}, t)
        for obj, lanes in (("mem:S/episode/m1", ("personal", "pending")), ("mem:S/episode/m2", ("pending", "work")),
                           ("mem:S/episode/m3", ("pending",))):
            for i, lane in enumerate(lanes):
                _ins(led, "lane_notes", {"object": obj, "lane": lane, "at": t + i, "seq": "@seq"}, t)
        state = led.state()
        assert [(r.object, r.subject) for r in state.self_claims] == [("mem:S/episode/m1", "person:amy")]
        assert sorted(led.pending_lane_notes()) == ["mem:S/episode/m1", "mem:S/episode/m3"]
    finally:
        led.close()


# ---------------------------------------------------------------- threads and the reader

def test_a_state_is_safe_across_threads(tmp_path):
    synthetic_ledger(tmp_path, 600, records=True)
    _with_agent(tmp_path)
    led = Ledger.open_read_only(tmp_path)
    try:
        state = led.state()
        want = decide_bulk(state, _bulk(_mems(600)))
        errors = []

        def work(offset):
            try:
                for rep in range(3):
                    objs = _mems(600)[offset::2]
                    for o in objs:
                        d = decide(state, permissions.Use(requester=RIO, place=HOME, obj=o, copy="store:house",
                                                          action="recall", purpose="care-coordination", at=AT))
                        assert d.allowed == want.allowed
            except BaseException as e:      # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=work, args=(i,)) for i in (0, 1)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors, errors
    finally:
        led.close()


def test_a_state_closes_its_reader(tmp_path):
    synthetic_ledger(tmp_path, 5)
    led = Ledger.open_read_only(tmp_path)
    try:
        state = led.state()
        state.subjects.get("mem:S/episode/m1")
        conns = [state._loader.conn, state.seq_at._conn]
        del state
        gc.collect()
        for c in conns:
            with pytest.raises(sqlite3.ProgrammingError):
                c.execute("SELECT 1")
    finally:
        led.close()
