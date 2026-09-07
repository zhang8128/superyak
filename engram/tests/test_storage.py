"""Tests for engram storage layer — 12 cases covering CRUD, vectors, FTS, CTE, cascades."""

from __future__ import annotations

import uuid
import sqlite3

import pytest
from datetime import datetime, timezone

import storage as storage_module
from storage import Storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSchemaAndPragmas:
    def test_schema_created(self, tmp_db):
        """All expected tables exist after init."""
        cur = tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger') ORDER BY name"
        )
        names = {row[0] for row in cur.fetchall()}
        for expected in [
            "entities", "relationships", "episodes", "episode_entities",
            "schema_version", "meta", "entity_fts",
        ]:
            assert expected in names, f"missing table: {expected}"

    def test_pragmas_set(self, tmp_db):
        """WAL mode, foreign_keys ON, busy_timeout 5000."""
        journal = tmp_db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal == "wal"
        fk = tmp_db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        bt = tmp_db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert bt == 5000


class TestEntityCRUD:
    def test_add_get_entity(self, tmp_db, sample_entity, fake_embedding):
        """Round-trip add + get."""
        emb = fake_embedding()
        tmp_db.add_entity(**sample_entity, embedding=emb)
        got = tmp_db.get_entity(sample_entity["id"])
        assert got is not None
        assert got["name"] == "Storage"
        assert got["entity_type"] == "class"
        assert got["description"] == sample_entity["description"]

    def test_delete_entity_cascades(self, tmp_db, fake_embedding):
        """Deleting an entity removes its relationships and episode links."""
        emb = fake_embedding()
        tmp_db.add_entity("a", "A", "class", embedding=emb)
        tmp_db.add_entity("b", "B", "class", embedding=fake_embedding())
        tmp_db.add_relationship("r1", "a", "b", "calls", valid_from=_now())
        tmp_db.add_episode("ep1", "sess", "content", "conversation", fake_embedding(), ["a"])

        tmp_db.delete_entity("a")

        assert tmp_db.get_entity("a") is None
        rels = tmp_db.get_relationships("a")
        assert len(rels) == 0
        links = tmp_db.conn.execute(
            "SELECT * FROM episode_entities WHERE entity_id = 'a'"
        ).fetchall()
        assert len(links) == 0


class TestRelationships:
    def test_add_relationship_with_validity(self, tmp_db, fake_embedding):
        """Add a relationship with valid_from, retrievable."""
        tmp_db.add_entity("a", "A", "func", embedding=fake_embedding())
        tmp_db.add_entity("b", "B", "func", embedding=fake_embedding())
        now = _now()
        tmp_db.add_relationship("r1", "a", "b", "calls", valid_from=now, weight=0.8)

        rels = tmp_db.get_relationships("a")
        assert len(rels) == 1
        assert rels[0]["rel_type"] == "calls"
        assert rels[0]["weight"] == 0.8

    def test_invalidate_relationship(self, tmp_db, fake_embedding):
        """Invalidated relationship excluded by valid_only filter."""
        tmp_db.add_entity("a", "A", "func", embedding=fake_embedding())
        tmp_db.add_entity("b", "B", "func", embedding=fake_embedding())
        tmp_db.add_relationship("r1", "a", "b", "calls", valid_from=_now())

        tmp_db.invalidate_relationship("r1")

        valid = tmp_db.get_relationships("a", valid_only=True)
        assert len(valid) == 0
        all_rels = tmp_db.get_relationships("a", valid_only=False)
        assert len(all_rels) == 1


class TestEpisodes:
    def test_add_episode_with_entity_links(self, tmp_db, fake_embedding):
        """Episode linked to entities via junction table."""
        tmp_db.add_entity("e1", "Foo", "class", embedding=fake_embedding())
        tmp_db.add_entity("e2", "Bar", "class", embedding=fake_embedding())
        tmp_db.add_episode("ep1", "s1", "discussed Foo and Bar", "conversation",
                           fake_embedding(), ["e1", "e2"])

        links = tmp_db.conn.execute(
            "SELECT entity_id FROM episode_entities WHERE episode_id = 'ep1' ORDER BY entity_id"
        ).fetchall()
        assert [r[0] for r in links] == ["e1", "e2"]


class TestVectorSearch:
    def test_search_vectors(self, tmp_db, fake_embedding):
        """Add entities with embeddings, search returns nearest."""
        # Use a known embedding for the query target
        target = [0.0] * 768
        target[0] = 1.0
        near = list(target)  # identical
        far = [0.0] * 768
        far[1] = 1.0  # orthogonal

        tmp_db.add_entity("near", "Near", "class", embedding=near)
        tmp_db.add_entity("far", "Far", "class", embedding=far)

        results = tmp_db.search_vectors("entity", target, k=2)
        assert len(results) >= 1
        # Nearest should be "near"
        assert results[0][0] == "near"


class TestFTS:
    def test_search_fts(self, tmp_db, fake_embedding):
        """FTS MATCH query works via triggers."""
        tmp_db.add_entity("e1", "StorageManager", "class",
                          description="Manages SQLite storage", embedding=fake_embedding())
        tmp_db.add_entity("e2", "NetworkClient", "class",
                          description="HTTP client wrapper", embedding=fake_embedding())

        results = tmp_db.search_fts("storage")
        assert "e1" in results  # search_fts returns entity IDs


class TestTraversal:
    def test_traverse_bidirectional(self, tmp_db, fake_embedding):
        """A->B->C: traverse from B finds both A and C."""
        for nid in ("a", "b", "c"):
            tmp_db.add_entity(nid, nid.upper(), "node", embedding=fake_embedding())
        now = _now()
        tmp_db.add_relationship("r1", "a", "b", "links", valid_from=now)
        tmp_db.add_relationship("r2", "b", "c", "links", valid_from=now)

        found = tmp_db.traverse("b", max_depth=2)
        found_ids = {e["id"] for e in found}
        assert "a" in found_ids
        assert "c" in found_ids

    def test_traverse_respects_validity(self, tmp_db, fake_embedding):
        """Invalid relationships excluded from traversal."""
        for nid in ("a", "b", "c"):
            tmp_db.add_entity(nid, nid.upper(), "node", embedding=fake_embedding())
        now = _now()
        tmp_db.add_relationship("r1", "a", "b", "links", valid_from=now)
        tmp_db.add_relationship("r2", "b", "c", "links", valid_from=now)
        tmp_db.invalidate_relationship("r2")

        found = tmp_db.traverse("b", max_depth=2)
        found_ids = {e["id"] for e in found}
        assert "a" in found_ids
        assert "c" not in found_ids


class TestMigration:
    def test_migration_versioning(self, tmp_db):
        """schema_version tracks applied migrations."""
        row = tmp_db.conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] >= 1


def test_storage_uses_resource_migrations_when_directory_is_not_explicit(
    tmp_path, monkeypatch,
):
    migrations = tmp_path / "installed" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_marker.sql").write_text(
        "CREATE TABLE installed_migration_marker(id INTEGER);\n"
    )
    monkeypatch.setattr(
        storage_module,
        "resource_path",
        lambda relative: migrations if relative == "migrations" else None,
    )

    store = Storage(str(tmp_path / "graph.db"))
    try:
        marker = store.conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='installed_migration_marker'"
        ).fetchone()
        assert marker is not None
    finally:
        store.close()


def test_close_retains_failed_cold_connection_and_closes_main_once(
    tmp_path, caplog,
):
    """A failed exact cold handle is retryable after the main DB is closed."""
    store = Storage(str(tmp_path / "graph.db"))

    class ColdConnection:
        def __init__(self):
            self.attempts = 0

        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise sqlite3.OperationalError("private cold close detail")

    cold = ColdConnection()
    store._cold_conn = cold

    with pytest.raises(sqlite3.OperationalError, match="private cold close detail"):
        store.close()

    assert store._cold_conn is cold
    assert cold.attempts == 1
    assert "private cold close detail" not in caplog.text
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        store.conn.execute("SELECT 1")

    caplog.clear()
    with caplog.at_level("WARNING", logger="engram.storage"):
        store.close()
        store.close()

    assert cold.attempts == 2
    assert store._cold_conn is None
    assert not any("WAL checkpoint failed" in record.message for record in caplog.records)


def test_close_checkpoint_warning_is_type_only(tmp_path, caplog):
    store = Storage(str(tmp_path / "graph.db"))
    real_connection = store.conn

    class CheckpointFailure:
        def execute(self, sql):
            assert sql == "PRAGMA wal_checkpoint(TRUNCATE)"
            raise sqlite3.OperationalError("private checkpoint detail")

        def close(self):
            real_connection.close()

    store.conn = CheckpointFailure()

    with caplog.at_level("WARNING", logger="engram.storage"):
        store.close()

    assert "private checkpoint detail" not in caplog.text
    assert any(
        record.message == "WAL checkpoint failed on close (OperationalError)"
        for record in caplog.records
    )


def test_failed_migration_rolls_back_schema_and_version(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_partial.sql").write_text(
        "CREATE TABLE half_applied(id INTEGER);\nTHIS IS NOT SQL;\n"
    )
    db_path = tmp_path / "graph.db"

    with pytest.raises(sqlite3.OperationalError, match='near "THIS"'):
        Storage(str(db_path), migrations_dir=str(migrations))

    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='half_applied'"
    ).fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0
    conn.close()


def test_storage_transaction_defers_helper_commits_and_rolls_back(tmp_db):
    episode_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="injected"):
        with tmp_db.transaction():
            tmp_db.add_episode(
                id=episode_id,
                session_id="transaction-test",
                content="This write must roll back with the outer unit of work.",
                embedding=[0.0] * 768,
            )
            raise RuntimeError("injected")

    assert tmp_db.get_episode(episode_id) is None
    assert tmp_db.conn.in_transaction is False


def test_storage_transaction_rolls_back_when_outer_commit_fails(tmp_db):
    class CommitFailingConnection:
        def __init__(self, conn):
            self._conn = conn
            self.rollback_calls = 0

        @property
        def in_transaction(self):
            return self._conn.in_transaction

        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

        def rollback(self):
            self.rollback_calls += 1
            self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    episode_id = str(uuid.uuid4())
    failing_conn = CommitFailingConnection(tmp_db.conn)
    tmp_db.conn = failing_conn

    with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
        with tmp_db.transaction():
            tmp_db.add_episode(
                id=episode_id,
                session_id="transaction-test",
                content="This write must roll back when the outer commit fails.",
                embedding=[0.0] * 768,
            )

    assert failing_conn.rollback_calls == 1
    assert failing_conn.in_transaction is False
    assert tmp_db.get_episode(episode_id) is None


def test_v3_migration_creates_tables(tmp_db):
    """v3 migration creates semantics, instincts, memory_log tables."""
    tables = {r[0] for r in tmp_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "semantics" in tables
    assert "instincts" in tables
    assert "memory_log" in tables
    assert "semantic_sources" in tables
    assert "instinct_sources" in tables


def test_v3_migration_adds_episode_columns(tmp_db):
    """v3 migration adds context, accessed_count, compressed columns to episodes."""
    cols = {r[1] for r in tmp_db.conn.execute("PRAGMA table_info(episodes)").fetchall()}
    assert "context" in cols
    assert "accessed_count" in cols
    assert "compressed" in cols
    assert "last_accessed" in cols


def test_add_episode_v3(tmp_db, fake_embedding):
    """Episode with context and embedding stores and retrieves correctly."""
    emb = fake_embedding()
    tmp_db.add_episode(
        id="ep-1", session_id="s1", content="learned about SQLite WAL mode",
        embedding=emb, context={"tool_context": "reading docs", "branch": "main"},
    )
    row = tmp_db.conn.execute("SELECT * FROM episodes WHERE id='ep-1'").fetchone()
    assert dict(row)["compressed"] == 0
    assert dict(row)["accessed_count"] == 0
    import json
    ctx = json.loads(dict(row)["context"])
    assert ctx["branch"] == "main"


def test_mark_episodes_compressed(tmp_db, fake_embedding):
    tmp_db.add_episode(id="ep-1", session_id="s1", content="a", embedding=fake_embedding())
    tmp_db.add_episode(id="ep-2", session_id="s1", content="b", embedding=fake_embedding())
    tmp_db.mark_episodes_compressed(["ep-1", "ep-2"])
    rows = tmp_db.conn.execute(
        "SELECT id, compressed FROM episodes WHERE compressed=1"
    ).fetchall()
    assert len(rows) == 2


def test_get_uncompressed_episodes(tmp_db, fake_embedding):
    tmp_db.add_episode(id="ep-1", session_id="s1", content="a", embedding=fake_embedding())
    tmp_db.add_episode(id="ep-2", session_id="s1", content="b", embedding=fake_embedding())
    tmp_db.mark_episodes_compressed(["ep-1"])
    uncompressed = tmp_db.get_uncompressed_episodes()
    assert len(uncompressed) == 1
    assert uncompressed[0]["id"] == "ep-2"


def test_increment_episode_access(tmp_db, fake_embedding):
    tmp_db.add_episode(id="ep-1", session_id="s1", content="a", embedding=fake_embedding())
    tmp_db.increment_episode_access("ep-1")
    row = tmp_db.conn.execute("SELECT accessed_count FROM episodes WHERE id='ep-1'").fetchone()
    assert row[0] == 1


def test_episode_fts_sync(tmp_db, fake_embedding):
    """FTS trigger should auto-index episode content."""
    tmp_db.add_episode(id="ep-1", session_id="s1", content="SQLite WAL mode is important",
                       embedding=fake_embedding())
    results = tmp_db.search_episode_fts("SQLite")
    assert "ep-1" in results


def test_add_semantic(tmp_db, fake_embedding):
    emb = fake_embedding()
    tmp_db.add_episode(id="ep-1", session_id="s1", content="test", embedding=emb)
    tmp_db.add_semantic(
        id="sem-1", content="project uses SQLite", kind="fact",
        confidence=0.5, embedding=emb, source_episode_ids=["ep-1"],
    )
    row = tmp_db.get_semantic("sem-1")
    assert row is not None
    assert row["kind"] == "fact"
    assert row["confidence"] == 0.5
    assert "ep-1" in row["source_episode_ids"]


def test_reinforce_semantic(tmp_db, fake_embedding):
    tmp_db.add_semantic(
        id="sem-1", content="project uses SQLite", kind="fact",
        confidence=0.5, embedding=fake_embedding(), source_episode_ids=[],
    )
    tmp_db.add_episode(id="ep-2", session_id="s1", content="test", embedding=fake_embedding())
    tmp_db.reinforce_semantic("sem-1", additional_episode_ids=["ep-2"])
    row = tmp_db.get_semantic("sem-1")
    assert row["reinforced_count"] == 1
    assert row["confidence"] == pytest.approx(0.6)  # 0.5 + 0.1


def test_contradict_semantic(tmp_db, fake_embedding):
    tmp_db.add_semantic(
        id="sem-1", content="old fact", kind="fact",
        confidence=0.7, embedding=fake_embedding(), source_episode_ids=[],
    )
    tmp_db.add_semantic(
        id="sem-2", content="new fact", kind="fact",
        confidence=0.9, embedding=fake_embedding(), source_episode_ids=[],
    )
    tmp_db.contradict_semantic("sem-1", contradicted_by="sem-2")
    row = tmp_db.get_semantic("sem-1")
    assert row["contradicted_by"] == "sem-2"


def test_semantic_fts_sync(tmp_db, fake_embedding):
    """FTS trigger should auto-index semantic content."""
    tmp_db.add_semantic(
        id="sem-1", content="SQLite is used for storage", kind="fact",
        confidence=0.5, embedding=fake_embedding(), source_episode_ids=[],
    )
    results = tmp_db.search_semantic_fts("SQLite")
    assert "sem-1" in results


def test_search_semantic_vectors(tmp_db, fake_embedding):
    emb = fake_embedding()
    tmp_db.add_semantic(
        id="sem-1", content="test", kind="fact",
        confidence=0.5, embedding=emb, source_episode_ids=[],
    )
    results = tmp_db.search_vectors("semantic", emb, k=5)
    assert len(results) >= 1
    assert results[0][0] == "sem-1"


def test_get_active_semantics(tmp_db, fake_embedding):
    tmp_db.add_semantic(id="s1", content="active", kind="fact", confidence=0.7,
                        embedding=fake_embedding(), source_episode_ids=[])
    tmp_db.add_semantic(id="s2", content="contradicted", kind="fact", confidence=0.5,
                        embedding=fake_embedding(), source_episode_ids=[])
    tmp_db.contradict_semantic("s2", contradicted_by="s1")
    active = tmp_db.get_active_semantics()
    assert len(active) == 1
    assert active[0]["id"] == "s1"


def test_add_instinct(tmp_db):
    tmp_db.add_instinct(
        id="inst-1", trigger="editing MCP server files",
        action="remind about restart", source_semantic_ids=["sem-1"],
    )
    row = tmp_db.get_instinct("inst-1")
    assert row is not None
    assert row["strength"] == 0.5
    assert row["fired_count"] == 0


def test_update_instinct_strength(tmp_db):
    tmp_db.add_instinct(id="inst-1", trigger="t", action="a", source_semantic_ids=[])
    tmp_db.update_instinct_followed("inst-1")  # +0.05
    row = tmp_db.get_instinct("inst-1")
    assert row["strength"] == pytest.approx(0.55)
    assert row["followed_count"] == 1

    tmp_db.update_instinct_overridden("inst-1")  # -0.05 (symmetric with follow)
    row = tmp_db.get_instinct("inst-1")
    assert row["strength"] == pytest.approx(0.50)
    assert row["overridden_count"] == 1


def test_get_all_instincts(tmp_db):
    tmp_db.add_instinct(id="i1", trigger="t1", action="a1", source_semantic_ids=[])
    tmp_db.add_instinct(id="i2", trigger="t2", action="a2", source_semantic_ids=[])
    instincts = tmp_db.get_all_instincts()
    assert len(instincts) == 2


def test_add_log_entry(tmp_db):
    tmp_db.add_log_entry(
        id="log-1", event_type="remember", layer="episode",
        target_ids=["ep-1"], context={"session_id": "s1"},
    )
    rows = tmp_db.conn.execute("SELECT * FROM memory_log").fetchall()
    assert len(rows) == 1


def test_get_log_entries(tmp_db):
    tmp_db.add_log_entry(id="l1", event_type="remember", layer="episode", target_ids=["ep-1"])
    tmp_db.add_log_entry(id="l2", event_type="recall", layer="episode", target_ids=["ep-1"])
    tmp_db.add_log_entry(id="l3", event_type="recall", layer="semantic", target_ids=["sem-1"])
    entries = tmp_db.get_log_entries(event_type="recall")
    assert len(entries) == 2


def test_update_log_outcome(tmp_db):
    tmp_db.add_log_entry(
        id="l1", event_type="recall", layer="episode",
        target_ids=["ep-1"], context={"recall_id": "r1"},
    )
    tmp_db.update_log_outcome("r1", "used")
    row = tmp_db.conn.execute("SELECT outcome FROM memory_log WHERE id='l1'").fetchone()
    assert row[0] == "used"


def test_fts_sanitizes_special_characters(tmp_db, fake_embedding):
    """FTS queries with special characters should not crash."""
    tmp_db.add_episode(
        id="ep-fts", session_id="s1", content="user prefers dark mode",
        embedding=fake_embedding(),
    )
    # Queries with FTS5 special chars should not raise
    for query in ["dark AND mode", 'user "prefers"', "NOT dark", "mode*", "(dark)"]:
        results = tmp_db.search_episode_fts(query)
        # Should return results or empty list, never raise
        assert isinstance(results, list)


def test_fts_finds_matching_content(tmp_db, fake_embedding):
    """FTS should find episodes matching query terms."""
    tmp_db.add_episode(
        id="ep-fts2", session_id="s1", content="python decorators are useful",
        embedding=fake_embedding(),
    )
    results = tmp_db.search_episode_fts("python decorators")
    assert "ep-fts2" in results


def test_semantic_auto_generated_flag(tmp_db, fake_embedding):
    """Semantics can be flagged as auto-generated."""
    emb = fake_embedding()
    tmp_db.add_semantic(
        id="s-auto", content="auto content", kind="fact",
        confidence=0.5, embedding=emb, source_episode_ids=[],
        auto_generated=True,
    )
    tmp_db.add_semantic(
        id="s-human", content="human content", kind="fact",
        confidence=0.5, embedding=emb, source_episode_ids=[],
        auto_generated=False,
    )
    auto = tmp_db.get_semantic("s-auto")
    human = tmp_db.get_semantic("s-human")
    assert auto["auto_generated"] == 1
    assert human["auto_generated"] == 0


def test_instinct_override_symmetric(tmp_db):
    """Override penalty should be -0.05, same magnitude as follow bonus."""
    tmp_db.add_instinct(id="i-sym", trigger="t", action="a", source_semantic_ids=[])
    tmp_db.update_instinct_overridden("i-sym")
    row = tmp_db.get_instinct("i-sym")
    assert row["strength"] == pytest.approx(0.45)


# --- Decay and forgetting ---

def test_apply_decay_power_law(tmp_db, fake_embedding):
    """Power-law decay: old untouched episodes weaken, recently accessed stay strong."""
    from datetime import datetime, timezone, timedelta

    # Episode created 7 days ago, never accessed
    tmp_db.add_episode(id="ep-old", session_id="s1", content="old memory", embedding=fake_embedding())
    old_time = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    tmp_db.conn.execute(
        "UPDATE episodes SET created_at = ?, last_accessed = NULL, accessed_count = 0 WHERE id = 'ep-old'",
        (old_time,),
    )

    # Episode created 7 days ago but accessed 1 hour ago, 10 times
    tmp_db.add_episode(id="ep-active", session_id="s1", content="active memory", embedding=fake_embedding())
    recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    tmp_db.conn.execute(
        "UPDATE episodes SET created_at = ?, last_accessed = ?, accessed_count = 10 WHERE id = 'ep-active'",
        (old_time, recent_time),
    )
    tmp_db.conn.commit()

    affected = tmp_db.apply_decay()
    assert affected == 2

    old_strength = tmp_db.conn.execute("SELECT decay_strength FROM episodes WHERE id='ep-old'").fetchone()[0]
    active_strength = tmp_db.conn.execute("SELECT decay_strength FROM episodes WHERE id='ep-active'").fetchone()[0]

    # Active episode should be much stronger than old untouched one
    assert active_strength > old_strength
    assert active_strength > 0.5  # recently accessed stays strong
    assert old_strength < 0.5    # old untouched episode has decayed


def test_decay_skips_near_zero(tmp_db, fake_embedding):
    """Episodes with strength < 0.01 should not be updated (already dead)."""
    tmp_db.add_episode(id="ep-dead", session_id="s1", content="dead", embedding=fake_embedding())
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.005 WHERE id = 'ep-dead'")
    tmp_db.conn.commit()

    affected = tmp_db.apply_decay()
    assert affected == 0


def test_prune_decayed(tmp_db, fake_embedding):
    """Pruning should move compressed episodes below threshold to cold storage."""
    tmp_db.add_episode(id="ep-weak", session_id="s1", content="weak episode text", embedding=fake_embedding())
    tmp_db.mark_episodes_compressed(["ep-weak"])
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.01 WHERE id = 'ep-weak'")
    tmp_db.conn.commit()

    pruned = tmp_db.prune_decayed(threshold=0.05)
    assert pruned == 1
    # Gone from main db
    assert tmp_db.get_episode("ep-weak") is None
    # Exists in cold storage
    cold = tmp_db._cold_storage()
    row = cold.execute("SELECT * FROM episodes WHERE id = 'ep-weak'").fetchone()
    assert row is not None
    assert row["content"] == "weak episode text"


def test_search_cold(tmp_db, fake_embedding):
    """Cold storage is searchable via FTS."""
    tmp_db.add_episode(id="ep-cold", session_id="s1", content="memories of the old garden", embedding=fake_embedding())
    tmp_db.mark_episodes_compressed(["ep-cold"])
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.01 WHERE id = 'ep-cold'")
    tmp_db.conn.commit()
    tmp_db.prune_decayed(threshold=0.05)

    results = tmp_db.search_cold("garden")
    assert len(results) == 1
    assert results[0]["content"] == "memories of the old garden"


def test_revive_episode(tmp_db, fake_embedding):
    """Reviving a cold episode restores it to main db with a fresh vector."""
    emb = fake_embedding()
    tmp_db.add_episode(id="ep-revive", session_id="s1", content="revivable memory", embedding=emb)
    tmp_db.mark_episodes_compressed(["ep-revive"])
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.01 WHERE id = 'ep-revive'")
    tmp_db.conn.commit()
    tmp_db.prune_decayed(threshold=0.05)
    assert tmp_db.get_episode("ep-revive") is None

    row = tmp_db.revive_episode("ep-revive", embed_fn=lambda content: emb)
    assert row is not None
    assert row["dormant"] == 0
    assert row["decay_strength"] == 0.5
    # Back in main db
    assert tmp_db.get_episode("ep-revive") is not None
    # Gone from cold
    cold = tmp_db._cold_storage()
    assert cold.execute("SELECT * FROM episodes WHERE id = 'ep-revive'").fetchone() is None


def test_prune_preserves_uncompressed(tmp_db, fake_embedding):
    """Uncompressed episodes should never be pruned, even if decayed."""
    tmp_db.add_episode(id="ep-unc", session_id="s1", content="uncompressed", embedding=fake_embedding())
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.001 WHERE id = 'ep-unc'")
    tmp_db.conn.commit()

    pruned = tmp_db.prune_decayed(threshold=0.05)
    assert pruned == 0
    assert tmp_db.get_episode("ep-unc") is not None


def test_access_updates_metadata(tmp_db, fake_embedding):
    """Accessing an episode should update accessed_count and last_accessed."""
    tmp_db.add_episode(id="ep-boost", session_id="s1", content="test", embedding=fake_embedding())

    tmp_db.increment_episode_access("ep-boost")

    row = tmp_db.conn.execute(
        "SELECT accessed_count, last_accessed FROM episodes WHERE id='ep-boost'"
    ).fetchone()
    assert row[0] == 1
    assert row[1] is not None  # last_accessed was set


def test_power_law_rewards_frequent_access(tmp_db, fake_embedding):
    """Frequently accessed episodes should score higher under power-law decay."""
    from datetime import datetime, timezone, timedelta

    # Both created same time, one accessed heavily
    old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

    tmp_db.add_episode(id="ep-idle", session_id="s1", content="idle", embedding=fake_embedding())
    tmp_db.conn.execute(
        "UPDATE episodes SET created_at = ?, accessed_count = 0 WHERE id = 'ep-idle'",
        (old_time,),
    )

    tmp_db.add_episode(id="ep-busy", session_id="s1", content="busy", embedding=fake_embedding())
    tmp_db.conn.execute(
        "UPDATE episodes SET created_at = ?, last_accessed = ?, accessed_count = 20 WHERE id = 'ep-busy'",
        (old_time, recent),
    )
    tmp_db.conn.commit()

    tmp_db.apply_decay()

    idle = tmp_db.conn.execute("SELECT decay_strength FROM episodes WHERE id='ep-idle'").fetchone()[0]
    busy = tmp_db.conn.execute("SELECT decay_strength FROM episodes WHERE id='ep-busy'").fetchone()[0]
    assert busy > idle


def test_add_instinct_context_feedback(tmp_db, fake_embedding):
    """Store context feedback for an instinct."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[sem_id], embedding=emb,
    )
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="building code",
        context_embedding=_pack_embedding(emb), followed=True,
    )
    feedback = tmp_db.get_instinct_context_feedback(inst_id)
    assert len(feedback) == 1
    assert feedback[0]["followed"] == 1
    assert feedback[0]["context_text"] == "building code"


def test_instinct_contextual_strength(tmp_db, fake_embedding):
    """Contextual strength should reflect follow/override ratio in similar contexts."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[sem_id], embedding=emb,
    )
    from storage import _pack_embedding
    packed = _pack_embedding(emb)
    for _ in range(3):
        tmp_db.add_instinct_context_feedback(
            instinct_id=inst_id, context_text="building",
            context_embedding=packed, followed=True,
        )
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="building",
        context_embedding=packed, followed=False,
    )
    ratio = tmp_db.get_context_follow_ratio(inst_id, context_text="building")
    assert ratio == pytest.approx(0.75)


def test_add_instinct_with_notice_implication(tmp_db, fake_embedding):
    """Instincts can be created with notice and implication fields."""
    emb = fake_embedding()
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[],
        notice="when the conversation shifts from building to reflecting",
        implication="communication style should match the mode",
        embedding=emb,
    )
    inst = tmp_db.get_instinct(inst_id)
    assert inst["notice"] == "when the conversation shifts from building to reflecting"
    assert inst["implication"] == "communication style should match the mode"


def test_prune_weak_instincts_cleans_context_vectors(tmp_db, fake_embedding):
    """Pruning weak instincts should also remove their context vectors and feedback."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = str(uuid.uuid4())
    tmp_db.add_instinct(
        id=inst_id, trigger="preference", action="weak instinct",
        source_semantic_ids=[sem_id], strength=0.05, embedding=emb,
    )
    tmp_db.add_instinct_context_vector(inst_id, emb)
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="test",
        context_embedding=_pack_embedding(emb), followed=False,
    )

    pruned = tmp_db.prune_weak_instincts(strength_threshold=0.1)
    assert pruned == 1

    # Context vectors and feedback should be gone too
    ctx_vec = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM instinct_context_vectors WHERE id = ?", (inst_id,)
    ).fetchone()[0]
    assert ctx_vec == 0
    feedback = tmp_db.get_instinct_context_feedback(inst_id)
    assert len(feedback) == 0


def test_challenge_instinct(tmp_db):
    """Challenge lowers strength more than a single override."""
    tmp_db.add_instinct(id="inst-c", trigger="t", action="a", source_semantic_ids=[])
    assert tmp_db.get_instinct("inst-c")["strength"] == pytest.approx(0.5)

    result = tmp_db.challenge_instinct("inst-c", strength_penalty=0.1)
    assert result is True
    assert tmp_db.get_instinct("inst-c")["strength"] == pytest.approx(0.4)

    # Challenge doesn't go below zero
    for _ in range(10):
        tmp_db.challenge_instinct("inst-c", strength_penalty=0.1)
    assert tmp_db.get_instinct("inst-c")["strength"] == pytest.approx(0.0)


def test_challenge_instinct_not_found(tmp_db):
    assert tmp_db.challenge_instinct("nonexistent") is False


def test_retire_instinct(tmp_db, fake_embedding):
    """Retire removes instinct and all associated data."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = str(uuid.uuid4())
    tmp_db.add_instinct(
        id=inst_id, trigger="preference", action="to be retired",
        source_semantic_ids=[sem_id], strength=0.5, embedding=emb,
    )
    tmp_db.add_instinct_context_vector(inst_id, emb)
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="ctx",
        context_embedding=_pack_embedding(emb), followed=True,
    )

    result = tmp_db.retire_instinct(inst_id)
    assert result is True

    # Everything should be gone
    assert tmp_db.get_instinct(inst_id) is None
    ctx_vec = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM instinct_context_vectors WHERE id = ?", (inst_id,)
    ).fetchone()[0]
    assert ctx_vec == 0
    assert len(tmp_db.get_instinct_context_feedback(inst_id)) == 0


def test_retire_instinct_not_found(tmp_db):
    assert tmp_db.retire_instinct("nonexistent") is False


def test_co_firing_tables_exist(tmp_db):
    """Migration 016 creates co-firing and cluster tables."""
    tables = {
        row[0]
        for row in tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "instinct_co_firing" in tables
    assert "instinct_clusters" in tables
    assert "instinct_cluster_members" in tables
    assert "lens_cluster_affinity" in tables


def test_record_co_fire(tmp_db):
    """Recording a co-fire creates or increments an edge."""
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "instinct one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "instinct two", [], embedding=emb)

    storage.record_co_fire("i1", "i2")
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge is not None
    assert edge["co_fire_count"] == 1
    assert edge["co_follow_count"] == 0

    # Second co-fire increments
    storage.record_co_fire("i1", "i2")
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 2


def test_record_co_fire_canonical_order(tmp_db):
    """Edge order is canonical — (i2, i1) reads the same as (i1, i2)."""
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("aaa", "preference", "first", [], embedding=emb)
    storage.add_instinct("zzz", "preference", "second", [], embedding=emb)

    storage.record_co_fire("zzz", "aaa")  # reversed order
    edge = storage.get_co_firing_edge("aaa", "zzz")
    assert edge is not None
    assert edge["co_fire_count"] == 1


def test_record_co_fire_with_outcome(tmp_db):
    """Co-fire with followed=True increments co_follow_count."""
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "two", [], embedding=emb)

    storage.record_co_fire("i1", "i2", followed=True)
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 1
    assert edge["co_follow_count"] == 1
    assert edge["co_override_count"] == 0

    storage.record_co_fire("i1", "i2", followed=False)
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 2
    assert edge["co_follow_count"] == 1
    assert edge["co_override_count"] == 1


def test_get_co_firing_neighbors(tmp_db):
    """Get all co-firing neighbors of an instinct."""
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("center", "preference", "center", [], embedding=emb)
    storage.add_instinct("n1", "preference", "neighbor 1", [], embedding=emb)
    storage.add_instinct("n2", "preference", "neighbor 2", [], embedding=emb)
    storage.add_instinct("isolated", "preference", "isolated", [], embedding=emb)

    storage.record_co_fire("center", "n1")
    storage.record_co_fire("center", "n2")

    neighbors = storage.get_co_firing_neighbors("center")
    neighbor_ids = {n["instinct_id"] for n in neighbors}
    assert neighbor_ids == {"n1", "n2"}
    assert "isolated" not in neighbor_ids


def test_create_and_get_cluster(tmp_db):
    storage = tmp_db
    storage.create_cluster("c1", maturity="seeded", temperament=0.5)
    cluster = storage.get_cluster("c1")
    assert cluster is not None
    assert cluster["maturity"] == "seeded"
    assert cluster["temperament"] == 0.5


def test_add_instinct_to_cluster(tmp_db):
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1", strength=0.7)
    members = storage.get_cluster_members("c1")
    assert len(members) == 1
    assert members[0]["instinct_id"] == "i1"
    assert members[0]["strength"] == 0.7


def test_get_instinct_cluster_strengths(tmp_db):
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.create_cluster("c2")
    storage.add_to_cluster("i1", "c1", strength=0.8)
    storage.add_to_cluster("i1", "c2", strength=0.3)
    strengths = storage.get_instinct_cluster_strengths("i1")
    assert len(strengths) == 2
    by_cluster = {s["cluster_id"]: s["strength"] for s in strengths}
    assert by_cluster["c1"] == 0.8
    assert by_cluster["c2"] == 0.3


def test_update_cluster_member_strength(tmp_db):
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1", strength=0.5)
    storage.update_cluster_member_strength("i1", "c1", 0.75)
    members = storage.get_cluster_members("c1")
    assert members[0]["strength"] == 0.75


def test_update_cluster_temperament(tmp_db):
    storage = tmp_db
    storage.create_cluster("c1", temperament=0.5)
    storage.update_cluster("c1", temperament=0.2)
    cluster = storage.get_cluster("c1")
    assert cluster["temperament"] == 0.2


def test_get_all_clusters(tmp_db):
    storage = tmp_db
    storage.create_cluster("c1")
    storage.create_cluster("c2")
    clusters = storage.get_all_clusters()
    assert len(clusters) == 2


def test_delete_cluster_cascades(tmp_db):
    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1")
    storage.delete_cluster("c1")
    assert storage.get_cluster("c1") is None
    assert storage.get_instinct_cluster_strengths("i1") == []


class TestCoreDemotionGrace:
    """Demoting a core episode must grant a fair decay run, not instant pruning."""

    def _add_old_compressed_episode(self, tmp_db, fake_embedding, ep_id):
        from datetime import timedelta
        tmp_db.add_episode(id=ep_id, session_id="s1", content=f"old episode {ep_id}",
                           embedding=fake_embedding())
        old = (datetime.now(timezone.utc) - timedelta(days=80)).isoformat()
        tmp_db.conn.execute(
            "UPDATE episodes SET created_at=?, last_accessed=?, compressed=1 WHERE id=?",
            (old, old, ep_id),
        )
        tmp_db.conn.commit()

    def test_unmark_core_grants_decay_grace(self, tmp_db, fake_embedding):
        self._add_old_compressed_episode(tmp_db, fake_embedding, "ep-demote")
        tmp_db.mark_core("ep-demote")

        tmp_db.unmark_core("ep-demote")
        tmp_db.apply_decay(min_interval_minutes=0)

        row = tmp_db.conn.execute(
            "SELECT decay_strength, last_accessed FROM episodes WHERE id='ep-demote'"
        ).fetchone()
        assert row["decay_strength"] >= 0.05, "demoted episode must not be instantly prunable"
        assert tmp_db.prune_decayed() == 0

    def test_unmark_core_batch_grants_decay_grace(self, tmp_db, fake_embedding):
        ids = ["ep-b1", "ep-b2", "ep-b3"]
        for ep_id in ids:
            self._add_old_compressed_episode(tmp_db, fake_embedding, ep_id)
        tmp_db.mark_core_batch(ids)

        assert tmp_db.unmark_core_batch(ids) == 3
        tmp_db.apply_decay(min_interval_minutes=0)

        for ep_id in ids:
            strength = tmp_db.conn.execute(
                "SELECT decay_strength FROM episodes WHERE id=?", (ep_id,)
            ).fetchone()[0]
            assert strength >= 0.05
        assert tmp_db.prune_decayed() == 0


# --- Memory lanes ---

def test_episode_lane_defaults_personal(tmp_db):
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="a plain memory")
    row = tmp_db.conn.execute("SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "personal"


def test_episode_lane_work_round_trip(tmp_db):
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="CommonWell uses OTP login", lane="work")
    row = tmp_db.conn.execute("SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "work"


def test_semantic_lane_round_trip(tmp_db):
    sid = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sid, content="pagination is cursor-based", kind="fact",
        confidence=0.5, embedding=[0.1] * 768, source_episode_ids=[], lane="work",
    )
    sem = tmp_db.get_semantic(sid)
    assert sem["lane"] == "work"


def test_set_episode_lanes_batch(tmp_db):
    ids = []
    for i in range(3):
        eid = str(uuid.uuid4())
        tmp_db.add_episode(id=eid, session_id="s", content=f"episode {i}")
        ids.append(eid)
    changed = tmp_db.set_episode_lanes(ids[:2], "work")
    assert changed == 2
    lanes = [r["lane"] for r in tmp_db.conn.execute(
        "SELECT lane FROM episodes").fetchall()]
    assert lanes.count("work") == 2 and lanes.count("personal") == 1


def test_set_episode_lanes_rejects_invalid_lane(tmp_db):
    with pytest.raises(ValueError):
        tmp_db.set_episode_lanes(["any-id"], "wrk")


def test_prune_preserves_lane_in_cold_storage(tmp_db, fake_embedding):
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="stale work detail",
                       embedding=fake_embedding(), lane="work")
    tmp_db.mark_episodes_compressed([eid])
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.01 WHERE id = ?", (eid,))
    tmp_db.conn.commit()
    pruned = tmp_db.prune_decayed(threshold=0.05)
    assert pruned == 1
    cold_row = tmp_db._cold_storage().execute(
        "SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert cold_row["lane"] == "work"


def test_revive_preserves_lane(tmp_db, fake_embedding):
    emb = fake_embedding()
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="stale work detail two",
                       embedding=emb, lane="work")
    tmp_db.mark_episodes_compressed([eid])
    tmp_db.conn.execute("UPDATE episodes SET decay_strength = 0.01 WHERE id = ?", (eid,))
    tmp_db.conn.commit()
    tmp_db.prune_decayed(threshold=0.05)
    assert tmp_db.get_episode(eid) is None
    tmp_db.revive_episode(eid, embed_fn=lambda content: emb)
    row = tmp_db.conn.execute("SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "work"


def test_migration_gap_is_filled_not_skipped(tmp_path):
    """A missing version below the high-water mark must still be applied.

    The runner used to select migrations with `version > MAX(version)`, so a
    gap was unrepairable: delete version N while N+1 is recorded and N never
    ran again. Gaps are reachable whenever two branches add migrations
    concurrently and one is renumbered before it lands.
    """
    from pathlib import Path as _Path

    from storage import Storage

    migrations_dir = str(_Path(__file__).resolve().parent.parent / "migrations")

    db_path = tmp_path / "gap.db"
    store = Storage(str(db_path), migrations_dir=migrations_dir)
    versions = {r[0] for r in store.conn.execute("SELECT version FROM schema_version")}
    assert len(versions) >= 2
    victim = sorted(versions)[-2]          # not the highest, so a gap is created
    store.conn.execute("DELETE FROM schema_version WHERE version = ?", (victim,))
    store.conn.commit()
    store.close()

    reopened = Storage(str(db_path), migrations_dir=migrations_dir)
    try:
        assert reopened.conn.execute(
            "SELECT 1 FROM schema_version WHERE version = ?", (victim,)
        ).fetchone(), f"migration {victim} was skipped because it sat below the max"
    finally:
        reopened.close()
