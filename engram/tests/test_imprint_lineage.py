import json
import sqlite3
import uuid

from cli import fork_instance
from store_identity import ancestry, independent, lineage, stamp_imprint, MAX_ANCESTRY, ORIGIN_IMPRINT
from tests.imprint_support import (GENOME_PARENT, fork_of, file_copy, genome_with_parent, iid, iid_of,
                                   imprint_of, new_store, old_fork_of, retro_store, unidentified_store)


def test_lineage_pairs_from_the_spec(tmp_path):
    g = new_store(tmp_path, "g"); y = fork_of(tmp_path, g, "y"); x = fork_of(tmp_path, y, "x")
    z = fork_of(tmp_path, g, "z"); i = imprint_of(tmp_path, x, "i"); i2 = imprint_of(tmp_path, x, "i2")
    L = lambda s: lineage(s.conn)
    for p, q in [(x, g), (x, z), (y, z), (i, g), (i, x), (i, i2), (i, fork_of(tmp_path, x, "f")),
                 (file_copy(tmp_path, g, "c"), g), (imprint_of(tmp_path, fork_of(tmp_path, y, "x2"), "i3"), g)]:
        assert independent(L(p), L(q)) is False
    assert L(i) == ({iid(i), iid(x), iid(y), iid(g)}, True)
    assert independent(L(new_store(tmp_path, "a")), L(new_store(tmp_path, "b"))) is True
    assert independent(L(old_fork_of(tmp_path, g, "w")), L(new_store(tmp_path, "u"))) is None

def test_stores_older_than_identity_are_never_complete(tmp_path):
    r = retro_store(tmp_path, "r", first=("e0", "2025-01-01T00:00:00+00:00"))
    r2 = retro_store(tmp_path, "r2", first=("e1", "2025-01-02T00:00:00+00:00"))   # its copy pruned e0 first
    assert ancestry(r.conn) == ([], False) and iid(r) != iid(r2)
    assert independent(lineage(r.conn), lineage(r2.conn)) is None
    assert lineage(imprint_of(tmp_path, r, "ir").conn).complete is False
    assert ancestry(unidentified_store(tmp_path, "n")) == ([], False)

def test_a_chain_longer_than_64_is_cut_and_incomplete(tmp_path):
    p = new_store(tmp_path, "p")
    p.conn.execute("INSERT OR REPLACE INTO meta VALUES ('ancestry', ?), ('ancestry_complete', 'true')",
                   (json.dumps([str(uuid.uuid4()) for _ in range(MAX_ANCESTRY)]),)); p.conn.commit()
    child = fork_of(tmp_path, p, "c")
    got, complete = ancestry(child.conn)
    assert len(got) == MAX_ANCESTRY and got[0] == iid(p) and complete is False

def test_stamp_imprint_writes_exactly_the_identity_keys_and_does_not_commit(tmp_path):
    src = fork_of(tmp_path, new_store(tmp_path, "g"), "src"); dst = new_store(tmp_path, "dst")
    stamp_imprint(dst.conn, iid(src), *ancestry(src.conn), "c0a8f5e2-0000-4000-8000-000000000000")
    assert dst.conn.in_transaction
    meta = dict(dst.conn.execute("SELECT key, value FROM meta"))
    assert meta["instance_id"] == "c0a8f5e2-0000-4000-8000-000000000000" and meta["instance_id_origin"] == ORIGIN_IMPRINT
    assert meta["forked_from_instance_id"] == iid(src) and json.loads(meta["ancestry"])[0] == iid(src)

def test_cli_fork_passes_the_parents_ancestry(tmp_path):
    engram_dir = genome_with_parent(tmp_path)          # genome forked from a recorded store
    fork_instance("w", engram_dir=engram_dir)
    conn = sqlite3.connect(engram_dir / "instances" / "w" / "graph.db")
    assert ancestry(conn)[0][:2] == [iid_of(engram_dir / "genome" / "graph.db"), GENOME_PARENT]
