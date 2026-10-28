"""SH-5: `Ledger.rebuild` reads the old log row by row, so its peak does not grow with the log (P 5.6, 15)."""
import gc
import tracemalloc

from permission_ledger import Ledger

MB = 1 << 20
OWNER = "person:andy"
COLL = "collection:andy/memories"


def test_rebuild_streams_the_log(tmp_path):
    led = Ledger.create(tmp_path / "old", "andy", now=1_000_000)
    led._append("collection", COLL, OWNER, "terminal",
                {"insert": [{"table": "collections", "row": {"id": COLL, "owner": OWNER, "created_seq": "@seq"}}]},
                at=1_000_001)
    pad = "x" * 100
    total = 0
    for batch in range(200):
        rows = [{"table": "collection_members",
                 "row": {"collection": COLL, "object": f"mem:S/episode/{pad}-{batch}-{i}", "backing": "person",
                         "added_seq": "@seq", "added_by": OWNER}} for i in range(1000)]
        led._append("collect", COLL, OWNER, "terminal", {"insert": rows}, at=1_000_002 + batch)
    total = led.conn.execute("SELECT SUM(LENGTH(body)) FROM ledger_log").fetchone()[0]
    assert total > 30 * MB
    gc.collect()
    tracemalloc.start()
    try:
        led.rebuild(tmp_path / "new")
        gc.collect()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    print(f"rebuild peak {peak / MB:.1f} MB over {total / MB:.1f} MB of bodies")
    assert peak < 16 * MB
    new = Ledger.open(tmp_path / "new")
    assert new.verify() is None and new.seq() == led.seq() == 202
    new.close()
    led.close()
