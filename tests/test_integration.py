"""Integration tests for engram v3 — full session flows."""
import pytest
import uuid

from storage import Storage
from compress import Compressor
from reflection import Reflector
from pathlib import Path


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


class FakeEmbeddingProvider:
    """Returns deterministic embeddings based on text content."""
    def embed(self, texts, **_kwargs):
        import hashlib
        results = []
        for text in texts:
            h = hashlib.md5(text.encode()).digest()
            emb = [float(b) / 255.0 for b in h] * 48  # 768 dims
            results.append(emb)
        return results


@pytest.fixture
def storage(tmp_path):
    db = Storage(str(tmp_path / "test.db"), migrations_dir=MIGRATIONS_DIR)
    yield db
    db.close()


@pytest.fixture
def embeddings():
    return FakeEmbeddingProvider()


@pytest.fixture
def compressor(storage, embeddings):
    return Compressor(storage, embeddings, config=None)


@pytest.fixture
def reflector(storage):
    return Reflector(storage, staleness_days=30)


def test_full_remember_recall_flow(storage, embeddings):
    """Remember episodes → recall → verify results come back."""
    emb = embeddings.embed(["SQLite WAL mode"])[0]
    storage.add_episode(id="ep-1", session_id="s1", content="SQLite uses WAL mode for concurrent reads",
                        embedding=emb, context={"branch": "main"})
    emb2 = embeddings.embed(["SQLite vec0"])[0]
    storage.add_episode(id="ep-2", session_id="s1", content="SQLite vec0 extension enables vector search",
                        embedding=emb2, context={"branch": "main"})

    # Search should find episodes via vector similarity
    query_emb = embeddings.embed(["SQLite features"])[0]
    results = storage.search_vectors("episode", query_emb, k=5)
    assert len(results) >= 1


def test_compression_creates_semantics(storage, embeddings, compressor):
    """Remember → compress → semantics exist."""
    emb = embeddings.embed(["SQLite fact"])[0]
    storage.add_episode(id="ep-1", session_id="s1", content="SQLite is great", embedding=emb)
    storage.add_episode(id="ep-2", session_id="s1", content="SQLite is reliable", embedding=emb)

    phase1 = compressor.cluster_episodes()
    assert len(phase1["clusters"]) >= 1

    summaries = [{"cluster_index": i, "content": f"SQLite cluster {i}", "kind": "fact"}
                 for i in range(len(phase1["clusters"]))]
    result = compressor.commit(phase1["compress_id"], summaries)
    assert result["semantics_created"] >= 1

    # Episodes should be marked compressed
    uncompressed = storage.get_uncompressed_episodes()
    assert len(uncompressed) == 0


def test_crash_recovery_auto_compress(storage, embeddings, compressor):
    """Uncompressed episodes from crashed session get auto-compressed."""
    emb = embeddings.embed(["crash test"])[0]
    storage.add_episode(id="ep-1", session_id="old-session", content="fact before crash", embedding=emb)
    storage.add_episode(id="ep-2", session_id="old-session", content="another fact", embedding=emb)
    # Simulate crash — episodes remain uncompressed

    # New session: auto_compress catches up
    result = compressor.auto_compress()
    assert result["episodes_processed"] == 2
    assert result["semantics_created"] >= 1

    # All episodes now compressed
    assert len(storage.get_uncompressed_episodes()) == 0


def test_instinct_lifecycle(storage, embeddings, compressor):
    """High-confidence semantic → instinct creation → strength tracking."""
    emb = embeddings.embed(["user preference"])[0]
    storage.add_semantic(
        id="sem-1", content="user prefers terse responses", kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )

    created = compressor._check_instinct_creation()
    assert created >= 1

    instincts = storage.get_all_instincts()
    assert len(instincts) >= 1

    inst_id = instincts[0]["id"]
    storage.update_instinct_followed(inst_id)
    row = storage.get_instinct(inst_id)
    assert row["strength"] > 0.5
    assert row["followed_count"] == 1

    storage.update_instinct_overridden(inst_id)
    row = storage.get_instinct(inst_id)
    assert row["overridden_count"] == 1


def test_reflection_after_session(storage, embeddings, reflector):
    """After remember + recall, reflection shows usage patterns."""
    emb = embeddings.embed(["test fact"])[0]
    storage.add_episode(id="ep-1", session_id="s1", content="test fact", embedding=emb)
    storage.increment_episode_access("ep-1")
    storage.increment_episode_access("ep-1")

    # Log a recall with no results (gap)
    storage.add_log_entry(id="l1", event_type="recall", layer="episode",
                          target_ids=[], context={"query": "nonexistent topic"})

    result = reflector.reflect()
    assert len(result["usage"]["most_accessed"]) >= 1
    assert result["usage"]["most_accessed"][0]["id"] == "ep-1"
    assert len(result["gaps"]) >= 1


def test_semantic_recall_after_compression(storage, embeddings, compressor):
    """After compression, semantics are searchable via vector similarity."""
    emb = embeddings.embed(["important fact"])[0]
    storage.add_episode(id="ep-1", session_id="s1", content="important fact", embedding=emb)

    phase1 = compressor.cluster_episodes()
    compressor.commit(phase1["compress_id"], [
        {"cluster_index": 0, "content": "distilled important fact", "kind": "fact"}
    ])

    # Search semantic vectors
    query_emb = embeddings.embed(["important"])[0]
    results = storage.search_vectors("semantic", query_emb, k=5)
    assert len(results) >= 1


def test_provenance_chain(storage, embeddings, compressor):
    """Episode → semantic provenance is traceable."""
    emb = embeddings.embed(["provenance test"])[0]
    storage.add_episode(id="ep-1", session_id="s1", content="provenance test", embedding=emb)

    phase1 = compressor.cluster_episodes()
    compressor.commit(phase1["compress_id"], [
        {"cluster_index": 0, "content": "provenance semantic", "kind": "fact"}
    ])

    # Find the created semantic
    active = storage.get_active_semantics()
    assert len(active) >= 1
    semantic = storage.get_semantic(active[0]["id"])
    assert "ep-1" in semantic["source_episode_ids"]


def test_vec0_corruption_recovery(tmp_path, embeddings):
    """Corrupt vec0 table is detected on init and rebuilt."""
    import sqlite3
    import sqlite_vec

    db_path = str(tmp_path / "test.db")

    # Phase 1: create a healthy DB with data
    store = Storage(db_path, migrations_dir=MIGRATIONS_DIR)
    emb = embeddings.embed(["healthy episode"])[0]
    store.add_episode(id="ep-1", session_id="s1", content="healthy episode", embedding=emb)
    results = store.search_vectors("episode", emb, k=1)
    assert len(results) == 1, "Vector search should work before corruption"
    store.close()

    # Phase 2: corrupt the episode_vectors vec0 table by dropping its shadow tables
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # Drop vec0 shadow tables to simulate corruption
    shadow_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'episode_vectors_%'"
    ).fetchall()
    for (table_name,) in shadow_tables:
        conn.execute(f"DROP TABLE IF EXISTS [{table_name}]")
    conn.commit()
    conn.close()

    # Phase 3: re-open — _check_vec0_health should detect and rebuild
    store2 = Storage(db_path, migrations_dir=MIGRATIONS_DIR)

    # The source episode still exists
    ep = store2.get_episode("ep-1")
    assert ep is not None
    assert ep["content"] == "healthy episode"

    # Vector table was rebuilt (empty — vectors lost, but table is usable)
    emb2 = embeddings.embed(["new data"])[0]
    store2.add_episode(id="ep-2", session_id="s2", content="new data", embedding=emb2)
    results = store2.search_vectors("episode", emb2, k=1)
    assert len(results) >= 1, "Vector search should work after rebuild"
    store2.close()


def test_contextual_instinct_lifecycle(storage, embeddings, compressor):
    """Full lifecycle: create semantic → instinct with notice/implication →
    contextual recall → context feedback → reflection shows per-context health."""
    # 1. Create high-confidence semantic
    sem_id = str(uuid.uuid4())
    storage.add_semantic(
        id=sem_id, content="prefer concise output when coding",
        kind="preference", confidence=0.85,
        embedding=embeddings.embed(["prefer concise output when coding"])[0],
        source_episode_ids=[],
    )

    # 2. Trigger instinct creation via compression
    ep_id = str(uuid.uuid4())
    storage.add_episode(id=ep_id, session_id="test",
                        content="filler episode for compression",
                        embedding=embeddings.embed(["filler episode for compression"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "filler episode", "kind": "fact", "action": "new"}])
    assert stats["instincts_created"] == 1

    # 3. Verify instinct has notice/implication
    instincts = storage.get_all_instincts()
    inst = instincts[-1]  # Most recently created
    assert inst["notice"] is not None
    assert inst["implication"] is not None
    assert "when" in inst["notice"].lower()

    # 4. Store context feedback in different contexts
    from storage import _pack_embedding
    build_emb = embeddings.embed(["building code"])[0]
    reflect_emb = embeddings.embed(["reflecting on design"])[0]

    # Follow in building context (3 times)
    for _ in range(3):
        storage.add_instinct_context_feedback(
            instinct_id=inst["id"], context_text="building",
            context_embedding=_pack_embedding(build_emb), followed=True,
        )
    # Override in reflecting context
    storage.add_instinct_context_feedback(
        instinct_id=inst["id"], context_text="reflecting",
        context_embedding=_pack_embedding(reflect_emb), followed=False,
    )

    # 5. Per-context health should show the difference
    from reflection import Reflector
    reflector = Reflector(storage)
    health = reflector.instinct_context_health()

    # Find our instinct's health
    inst_health = [h for h in health if h["id"] == inst["id"]]
    assert len(inst_health) == 1
    contexts = {c["context"]: c["follow_ratio"] for c in inst_health[0]["contexts"]}
    assert contexts["building"] == 1.0
    assert contexts["reflecting"] == 0.0

    # 6. Verify context follow ratio
    build_ratio = storage.get_context_follow_ratio(inst["id"], "building")
    assert build_ratio == 1.0
    reflect_ratio = storage.get_context_follow_ratio(inst["id"], "reflecting")
    assert reflect_ratio == 0.0


def test_wal_checkpoint_on_close(tmp_path):
    """close() checkpoints WAL, leaving no -wal file."""
    db_path = str(tmp_path / "test.db")
    store = Storage(db_path, migrations_dir=MIGRATIONS_DIR)
    # Write something to ensure WAL has data
    store.add_episode(id="ep-1", session_id="s1", content="wal test")
    store.close()

    wal_path = Path(db_path + "-wal")
    # After TRUNCATE checkpoint, WAL file should be empty or absent
    if wal_path.exists():
        assert wal_path.stat().st_size == 0
