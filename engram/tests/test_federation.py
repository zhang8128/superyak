"""Tests for federation foundation: content_hash and context columns (migration 007)."""

from __future__ import annotations

import hashlib


def test_episode_has_content_hash(tmp_db, fake_embedding):
    """Inserting an episode should populate content_hash with SHA-256 of content."""
    content = "learned about distributed engram federation"
    tmp_db.add_episode(
        id="ep-fed-1",
        session_id="s1",
        content=content,
        embedding=fake_embedding(),
    )
    row = tmp_db.conn.execute(
        "SELECT content_hash FROM episodes WHERE id = 'ep-fed-1'"
    ).fetchone()
    assert row is not None
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert row[0] == expected


def test_semantic_has_content_hash(tmp_db):
    """Inserting a semantic should populate content_hash with SHA-256 of content."""
    content = "engram uses nomic-embed-text-v1.5 for embeddings"
    tmp_db.add_semantic(
        id="sem-fed-1",
        content=content,
        kind="fact",
        confidence=0.8,
        embedding=[0.0] * 768,
        source_episode_ids=[],
    )
    row = tmp_db.conn.execute(
        "SELECT content_hash FROM semantics WHERE id = 'sem-fed-1'"
    ).fetchone()
    assert row is not None
    expected = hashlib.sha256(content.encode()).hexdigest()
    assert row[0] == expected


def test_instinct_has_content_hash_and_context(tmp_db):
    """Inserting an instinct should populate content_hash (SHA-256 of action) and context defaults to NULL."""
    action = "remind about MCP server restart when editing server.py"
    tmp_db.add_instinct(
        id="inst-fed-1",
        trigger="editing MCP server files",
        action=action,
        source_semantic_ids=[],
    )
    row = tmp_db.conn.execute(
        "SELECT content_hash, context FROM instincts WHERE id = 'inst-fed-1'"
    ).fetchone()
    assert row is not None
    expected = hashlib.sha256(action.encode()).hexdigest()
    assert row["content_hash"] == expected
    assert row["context"] is None


def test_mark_core_with_tier(tmp_db, fake_embedding):
    """mark_core(tier=1) and mark_core(tier=2) set the correct core values."""
    tmp_db.add_episode(
        id="ep-core-t1",
        session_id="s1",
        content="local core episode",
        embedding=fake_embedding(),
    )
    tmp_db.add_episode(
        id="ep-core-t2",
        session_id="s1",
        content="genome core episode",
        embedding=fake_embedding(),
    )

    tmp_db.mark_core("ep-core-t1", tier=1)
    tmp_db.mark_core("ep-core-t2", tier=2)

    row1 = tmp_db.conn.execute(
        "SELECT core FROM episodes WHERE id = 'ep-core-t1'"
    ).fetchone()
    row2 = tmp_db.conn.execute(
        "SELECT core FROM episodes WHERE id = 'ep-core-t2'"
    ).fetchone()

    assert row1[0] == 1
    assert row2[0] == 2


def test_get_core_episodes_both_tiers(tmp_db, fake_embedding):
    """get_core_episodes returns episodes marked with tier 1 and tier 2."""
    tmp_db.add_episode(
        id="ep-gc-regular",
        session_id="s1",
        content="regular episode — should not appear",
        embedding=fake_embedding(),
    )
    tmp_db.add_episode(
        id="ep-gc-t1",
        session_id="s1",
        content="local core — tier 1",
        embedding=fake_embedding(),
    )
    tmp_db.add_episode(
        id="ep-gc-t2",
        session_id="s1",
        content="genome core — tier 2",
        embedding=fake_embedding(),
    )

    tmp_db.mark_core("ep-gc-t1", tier=1)
    tmp_db.mark_core("ep-gc-t2", tier=2)

    core = tmp_db.get_core_episodes()
    core_ids = {ep["id"] for ep in core}

    assert "ep-gc-t1" in core_ids
    assert "ep-gc-t2" in core_ids
    assert "ep-gc-regular" not in core_ids


# ---------------------------------------------------------------------------
# Task 4: SignalBus tests
# ---------------------------------------------------------------------------

import tempfile
from pathlib import Path

import pytest

from federation import SignalBus


@pytest.fixture
def signal_bus(tmp_path):
    bus = SignalBus(tmp_path / "signals.db")
    yield bus
    bus.close()


def test_signals_db_creation(signal_bus):
    """Create SignalBus, send a message, verify inbox for another instance returns it."""
    bus = signal_bus
    msg_id = bus.send(
        from_instance="agi",
        to_instance="engram",
        msg_type="ping",
        content="hello from agi",
    )

    inbox = bus.inbox("engram")
    assert len(inbox) == 1
    msg = inbox[0]
    assert msg["id"] == msg_id
    assert msg["from_instance"] == "agi"
    assert msg["to_instance"] == "engram"
    assert msg["type"] == "ping"
    assert msg["content"] == "hello from agi"


def test_broadcast_vs_directed(signal_bus):
    """Send broadcast + 2 directed messages; verify each instance sees the right messages."""
    bus = signal_bus

    # Broadcast from agi — should reach blocks and why, but NOT agi itself
    broadcast_id = bus.send(
        from_instance="agi",
        to_instance=None,
        msg_type="announce",
        content="broadcast to all",
    )

    # Directed to blocks only
    blocks_id = bus.send(
        from_instance="agi",
        to_instance="blocks",
        msg_type="task",
        content="task for blocks",
    )

    # Directed to why only
    why_id = bus.send(
        from_instance="agi",
        to_instance="why",
        msg_type="question",
        content="question for why",
    )

    # agi's own inbox: excludes self-sent, so gets nothing
    agi_inbox = bus.inbox("agi")
    agi_ids = {m["id"] for m in agi_inbox}
    assert broadcast_id not in agi_ids
    assert blocks_id not in agi_ids
    assert why_id not in agi_ids

    # blocks inbox: broadcast + directed-to-blocks
    blocks_inbox = bus.inbox("blocks")
    blocks_ids = {m["id"] for m in blocks_inbox}
    assert broadcast_id in blocks_ids
    assert blocks_id in blocks_ids
    assert why_id not in blocks_ids

    # why inbox: broadcast + directed-to-why
    why_inbox = bus.inbox("why")
    why_ids = {m["id"] for m in why_inbox}
    assert broadcast_id in why_ids
    assert why_id in why_ids
    assert blocks_id not in why_ids


def test_mark_seen_and_threading(signal_bus):
    """Mark a message seen removes it from inbox; reply with in_reply_to threads correctly."""
    bus = signal_bus

    # engram sends a question to agi
    q_id = bus.send(
        from_instance="engram",
        to_instance="agi",
        msg_type="query",
        content="what is the current task?",
    )

    # agi's inbox should contain the question
    inbox_before = bus.inbox("agi")
    assert any(m["id"] == q_id for m in inbox_before)

    # agi marks the question as seen
    bus.mark_seen(q_id, "agi")

    # agi's inbox should no longer contain the question
    inbox_after = bus.inbox("agi")
    assert not any(m["id"] == q_id for m in inbox_after)

    # agi replies, threading back to the original question
    reply_id = bus.send(
        from_instance="agi",
        to_instance="engram",
        msg_type="reply",
        content="the current task is federation",
        in_reply_to=q_id,
    )

    # engram's inbox should contain the reply
    engram_inbox = bus.inbox("engram")
    reply_msgs = [m for m in engram_inbox if m["id"] == reply_id]
    assert len(reply_msgs) == 1
    assert reply_msgs[0]["in_reply_to"] == q_id


# ---------------------------------------------------------------------------
# Task 5: InstanceRegistry tests
# ---------------------------------------------------------------------------

def test_instance_registry(tmp_path):
    from federation import InstanceRegistry
    reg = InstanceRegistry(tmp_path / "instances.json")
    reg.register("agi", tmp_path / "agi" / "graph.db", forked_from="genome")
    reg.register("blocks", tmp_path / "blocks" / "graph.db", forked_from="genome")
    instances = reg.list()
    assert "agi" in instances
    assert "blocks" in instances
    assert instances["agi"]["forked_from"] == "genome"
    reg.remove("blocks")
    assert "blocks" not in reg.list()


# ---------------------------------------------------------------------------
# Task 6: sync_genome tests
# ---------------------------------------------------------------------------

def test_genome_sync(tmp_path):
    import hashlib
    from federation import sync_genome
    from storage import Storage

    # Set up genome DB with a genome-core episode
    genome_dir = tmp_path / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_episode(
        id="gep1", session_id="s1", content="user is a mathematician",
        episode_type="observation",
    )
    genome.mark_core("gep1", tier=2)
    genome.conn.commit()

    # Set up instance DB — empty
    inst_dir = tmp_path / "instance"
    inst_dir.mkdir()
    instance = Storage(str(inst_dir / "graph.db"))

    # Sync
    synced = sync_genome(genome_path=str(genome_dir / "graph.db"), instance_storage=instance)
    assert synced == 1

    # Episode should exist locally with core=2
    row = instance.conn.execute(
        "SELECT core, content FROM episodes WHERE content_hash = ?",
        (hashlib.sha256("user is a mathematician".encode()).hexdigest(),)
    ).fetchone()
    assert row is not None
    assert row["core"] == 2

    # Second sync should be idempotent
    synced2 = sync_genome(genome_path=str(genome_dir / "graph.db"), instance_storage=instance)
    assert synced2 == 0

    genome.close()
    instance.close()


# ---------------------------------------------------------------------------
# Task 7: process_inbox tests
# ---------------------------------------------------------------------------

def test_process_inbox(tmp_path):
    from federation import SignalBus, process_inbox
    from storage import Storage

    bus = SignalBus(tmp_path / "signals.db")
    bus.send("agi", "blocks", "instinct_formed", "prefer simple decomposition")
    bus.send("why", None, "semantic_promoted", "governance tick runs weekly")

    inst = Storage(str(tmp_path / "graph.db"))
    processed = process_inbox(bus, "blocks", inst)
    assert processed == 2

    rows = inst.conn.execute(
        "SELECT content, source FROM episodes WHERE source LIKE 'signal/%'"
    ).fetchall()
    assert len(rows) == 0
    assert inst.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0

    # Messages wait for the receiver's explicit choice to read or remember.
    assert len(bus.inbox("blocks")) == 2

    bus.close()
    inst.close()


# ---------------------------------------------------------------------------
# Task 12: Full federation lifecycle integration test
# ---------------------------------------------------------------------------

def test_full_federation_lifecycle(tmp_path):
    """End-to-end: create genome → fork instances → remember with genome=True →
    sync → send signals → process inbox → verify drift detection."""
    from storage import Storage
    from federation import SignalBus, InstanceRegistry, sync_genome, process_inbox
    from cli import fork_instance

    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()

    # 1. Create genome with initial knowledge
    genome_dir = engram_dir / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_episode(
        id="gep1", session_id="s1", content="user is a mathematician in healthcare",
        episode_type="observation",
    )
    genome.mark_core("gep1", tier=2)
    genome.conn.commit()
    genome.close()

    # 2. Fork two instances
    fork_instance("agi", engram_dir)
    fork_instance("blocks", engram_dir)

    # 3. Both instances should have the genome episode
    agi = Storage(str(engram_dir / "instances" / "agi" / "graph.db"))
    blocks = Storage(str(engram_dir / "instances" / "blocks" / "graph.db"))
    assert len(agi.get_core_episodes()) == 1
    assert len(blocks.get_core_episodes()) == 1

    # 4. Add local knowledge to agi (not shared)
    agi.add_episode(
        id="aep1", session_id="s2", content="arena fitness improves with diversity",
        episode_type="observation",
    )
    agi.conn.commit()

    # 5. Send signal from agi to blocks
    bus = SignalBus(engram_dir / "signals.db")
    bus.send("agi", "blocks", "instinct_formed", "prefer diverse strategy selection")

    # 6. Process blocks inbox
    processed = process_inbox(bus, "blocks", blocks)
    assert processed == 1

    # 7. Blocks leaves the message unread and never saves it automatically.
    signal_eps = blocks.conn.execute(
        "SELECT content, source FROM episodes WHERE source LIKE 'signal/%'"
    ).fetchall()
    assert len(signal_eps) == 0
    assert len(bus.inbox("blocks")) == 1

    # 8. Agi's local episode should NOT be in blocks
    agi_only = blocks.conn.execute(
        "SELECT 1 FROM episodes WHERE content = 'arena fitness improves with diversity'"
    ).fetchone()
    assert agi_only is None

    # 9. Add new genome-core episode
    genome2 = Storage(str(genome_dir / "graph.db"))
    genome2.add_episode(
        id="gep2", session_id="s3", content="system goal is bridging digital and biological",
        episode_type="observation",
    )
    genome2.mark_core("gep2", tier=2)
    genome2.conn.commit()
    genome2.close()

    # 10. Sync agi — should pick up new genome episode
    synced = sync_genome(str(genome_dir / "graph.db"), agi)
    assert synced == 1
    assert len(agi.get_core_episodes()) == 2

    bus.close()
    agi.close()
    blocks.close()
