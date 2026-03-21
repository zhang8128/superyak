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
