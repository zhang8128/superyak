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
