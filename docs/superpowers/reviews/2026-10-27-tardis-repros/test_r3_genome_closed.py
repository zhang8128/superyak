"""Repro: under a closed gate, genome sync writes copies with no kept-copy record, so they lose their co-subjects."""
from pathlib import Path


def test_genome_sync_under_closed_drops_subjects(tmp_path, monkeypatch):
    import federation
    import server
    from permission_ledger import Ledger, effective_gate
    from permissions import subjects_of
    from tests.permissions_support import genome_world

    led, genome_path, instance, ids = genome_world(tmp_path, mode="enforce")
    led.close()
    # The instance store loses its ledger mark (e.g. restored from a backup made before the raise): closed.
    instance.conn.execute("DELETE FROM meta WHERE key = 'permissions_ledger_id'")
    instance.conn.commit()
    gate = effective_gate(tmp_path, [Path(instance.db_path)])
    assert gate.mode == "closed", gate

    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "_storage", instance)
    monkeypatch.setattr(server, "_genome_db_path", genome_path)
    synced = server._sync_genome_kept(federation.sync_genome)
    print("synced under closed:", synced)
    assert synced == 1                                       # the sync ran under a closed gate
    [local] = [r["id"] for r in instance.conn.execute("SELECT id FROM episodes WHERE episode_type = 'genome_sync'")]
    led = Ledger.open(tmp_path)
    try:
        s = led.state()
        subs = subjects_of(s, f"mem:{ids.I}/episode/{local}", int(__import__("time").time()) + 10)
        src = subjects_of(s, f"mem:{ids.G}/episode/{ids.g1}", int(__import__("time").time()) + 10)
    finally:
        led.close()
    print("source subjects:", src, "copy subjects:", subs)
    assert "person:jenn" in src and "person:jenn" not in subs
    # And a later sync never repairs it: the episode is already present.
    assert federation.sync_genome(str(genome_path), instance, ledger=Ledger.open(tmp_path)) == 0
