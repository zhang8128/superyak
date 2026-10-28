"""Down-closure, the memories that ship and the links induced on them (store-copy spec I 5.2, 6.2, 6.4)."""
import pytest

import imprint_filter
from imprint_filter import (PlanRefused, Shipped, admissible, link_rows, semantic_rows, shipped, vector_rows)
from tests.imprint_support import (T, ctx, ep, new_store, peer_edge, prune, resonance, selection, sem,
                                   subdivision, vec)


def links_store(tmp_path):
    """Every link table with rows inside M and rows reaching outside it (M = the work-lane memories)."""
    s = new_store(tmp_path, "links")
    ep(s, "e-in"); ep(s, "e-in2"); ep(s, "e-out", lane="personal")
    sem(s, "s-in", sources=["e-in", "e-out"]); sem(s, "s-peer-in"); sem(s, "s-out", sources=["e-in"], lane="personal")
    resonance(s, "res-in", "e-in", "s-in", layer_b="semantic")
    resonance(s, "res-out", "e-in", "e-out")
    resonance(s, "res-after-t1", "e-in", "e-in2", at="2026-10-26T00:00:00+00:00")
    peer_edge(s, "s-peer-in", "s-in"); peer_edge(s, "s-out", "s-in"); peer_edge(s, "s-peer-in", "s-out")
    subdivision(s, "sub-in", "s-in", ["s-peer-in"])
    subdivision(s, "sub-out", "s-in", ["s-peer-in", "s-out"])
    subdivision(s, "sub-episode", "s-in", ["e-in"])
    subdivision(s, "sub-bad", "s-in", [])
    s.conn.execute("UPDATE subdivision_events SET peer_ids = 'not json' WHERE id = 'sub-bad'")
    s.conn.commit()
    return s


def shipped_all(s):
    """The work-lane memories, without going through admissible."""
    ids = lambda t: tuple(r[0] for r in s.conn.execute(f"SELECT id FROM {t} WHERE lane = 'work' ORDER BY id"))
    return Shipped(ids("episodes"), ids("semantics"))


def test_down_closure_over_recorded_sources(tmp_path):
    s = new_store(tmp_path, "s")
    for i in ("e-in", "e2", "gone"): ep(s, i)
    ep(s, "e-out", lane="personal")
    sem(s, "s-mixed", sources=["e-in", "e-out"]); sem(s, "s-whole", sources=["e-in", "e2"])
    sem(s, "s-none", sources=[]); sem(s, "s-pruned-one", sources=["e2", "gone"]); prune(s, "gone")
    adm = admissible(s.conn, selection(), ctx(s))
    assert set(adm.semantics) == {"s-whole", "s-pruned-one"}
    assert adm.counts["semantic_source_stays"] == 1 and adm.counts["semantic_unsourced"] == 1
    assert "s-none" in admissible(s.conn, selection(unsourced=True), ctx(s)).semantics


def test_layers_choose_what_ships_never_what_is_admissible(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "e1"); ep(s, "e2"); sem(s, "s1", sources=["e1"]); sem(s, "s2", sources=["e2"])
    sh = shipped(admissible(s.conn, selection(layers={"semantic"}, exclude={"e2"}), ctx(s)), selection(layers={"semantic"}))
    assert sh.episodes == () and sh.semantics == ("s1",)


def test_each_link_row_with_an_endpoint_outside_m_is_dropped(tmp_path):
    s = links_store(tmp_path)
    rows = link_rows(s.conn, selection(until=T("2026-10-25T18:00:00Z")), shipped_all(s))
    assert [r["episode_id"] for r in rows["semantic_sources"]] == ["e-in"]
    assert [r["id"] for r in rows["resonances"]] == ["res-in"]          # res-out and res-after-t1 dropped
    assert [r["peer_id"] for r in rows["semantic_peers"]] == ["s-peer-in"]
    assert [r["id"] for r in rows["subdivision_events"]] == ["sub-in"]


def test_a_resonance_before_the_window_is_dropped(tmp_path):
    s = links_store(tmp_path)
    rows = link_rows(s.conn, selection(since=T("2026-10-02T00:00:00Z")), shipped_all(s))
    assert list(rows["resonances"]) == []


def test_contradicted_by_is_cleared_when_it_names_a_semantic_that_stays(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "e1"); sem(s, "kept", sources=["e1"], contradicted_by="home-only")
    sem(s, "home-only", sources=["e1"], lane="personal")
    assert next(semantic_rows(s.conn, Shipped(("e1",), ("kept",))))["contradicted_by"] is None


def test_contradicted_by_is_kept_when_it_names_a_semantic_that_ships(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "e1")
    sem(s, "a", sources=["e1"], contradicted_by="b"); sem(s, "b", sources=["e1"])
    rows = list(semantic_rows(s.conn, Shipped(("e1",), ("b", "a"))))
    assert [(r["id"], r["contradicted_by"]) for r in rows] == [("b", None), ("a", "b")]      # memory order


def test_vector_rows_come_in_memory_order_one_batch_per_query(tmp_path):
    s = new_store(tmp_path, "s")
    for n, i in enumerate(("e1", "e2", "e3")): ep(s, i); vec(s, "episode", i, n)
    rows = list(vector_rows(s.conn, "episode", ["e3", "e1", "e2"]))
    assert [r["id"] for r in rows] == ["e3", "e1", "e2"]
    assert all(isinstance(r["embedding"], bytes) and len(r["embedding"]) == 768 * 4 for r in rows)
    assert list(vector_rows(s.conn, "semantic", ["nothing"])) == []


def test_members_and_refs(tmp_path):
    s = new_store(tmp_path, "s")
    sh = Shipped(("e2", "e1"), ("s1",))
    assert sh.members() == {("episode", "e1"), ("episode", "e2"), ("semantic", "s1")}
    assert list(sh.refs("src")) == ["mem:src/episode/e1", "mem:src/episode/e2", "mem:src/semantic/s1"]


def test_no_memories_or_too_many_is_refused(tmp_path, monkeypatch):
    s = new_store(tmp_path, "s")
    with pytest.raises(PlanRefused, match="no memories"):
        shipped(admissible(s.conn, selection(), ctx(s)), selection())
    for i in range(4): ep(s, f"e{i}")
    monkeypatch.setattr(imprint_filter, "MAX_MEMORIES", 3)
    with pytest.raises(PlanRefused, match="100,000"):
        shipped(admissible(s.conn, selection(), ctx(s)), selection())
