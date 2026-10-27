"""Repro: remember(genome=True) after an allowed imprint records the local kept copy, but not the genome copy."""
import server
from permission_ledger import Ledger
from permissions import Act, subjects_of
from storage import Storage
from tests.permissions_support import (  # noqa: F401
    ANDY, KEEP_LATER, KEEP_NOW, M1, M1_TEXT, HOME, deliver_m1_through, keep_world, keep_world_with_imprint_allowed)
from tests.test_recall_margins import engram_server_env  # noqa: F401


def test_genome_copy_of_a_kept_item_has_no_lineage(keep_world_with_imprint_allowed):
    w = keep_world_with_imprint_allowed
    server._genome_db_path.parent.mkdir(parents=True, exist_ok=True)
    genome = Storage(str(server._genome_db_path))
    gid = genome.instance_identity()["instance_id"]
    genome.close()
    led = Ledger.open(w.root)
    try:
        led.perform(Act("register-store", dict(instance_id=gid, name="genome", owner=ANDY, place=HOME,
                                                imprint_of=None)), actor=ANDY, channel="terminal", now=KEEP_LATER)
    finally:
        led.close()
    deliver_m1_through(w, "neighbors")
    out = server.remember(content=M1_TEXT, genome=True)
    assert "episode_id" in out, out
    kept = f"mem:{w.ids.PHC_STORE}/episode/{out['episode_id']}"
    g = Storage(str(server._genome_db_path))
    [gep] = [r["id"] for r in g.conn.execute("SELECT id FROM episodes WHERE episode_type = 'genome_write'")]
    g.close()
    gcopy = f"mem:{gid}/episode/{gep}"
    led = Ledger.open(w.root)
    try:
        led.perform(Act("add-subject", {"object": M1, "subject": "person:amy"}), actor=ANDY, channel="terminal",
                    now=KEEP_LATER)
        s = led.state()
    finally:
        led.close()
    print("copies:", {k: v for k, v in s.copies.items()})
    print("kept subjects:", subjects_of(s, kept, KEEP_NOW), "genome copy subjects:", subjects_of(s, gcopy, KEEP_NOW))
    assert s.copies.get(kept) == M1 and gcopy not in s.copies
    assert "person:amy" in subjects_of(s, kept, KEEP_NOW)
    assert "person:amy" not in subjects_of(s, gcopy, KEEP_NOW)
