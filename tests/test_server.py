"""Integration tests for the engram MCP server v3 tools — 14 tests."""

from __future__ import annotations

import math
import os
import textwrap
import uuid
from pathlib import Path

import pytest

from storage import Storage

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


# ---------------------------------------------------------------------------
# Fake embedding provider (deterministic, no model download)
# ---------------------------------------------------------------------------

class FakeEmbeddingProvider:
    def __init__(self, dim: int = 768):
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        import hashlib
        import random as _random

        h = hashlib.sha256(text.encode()).digest()
        rng = _random.Random(int.from_bytes(h[:8], "little"))
        vec = [rng.gauss(0, 1) for _ in range(self._dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Fixtures — wire up server module globals with temp DB
# ---------------------------------------------------------------------------

@pytest.fixture
def server_env(tmp_path, monkeypatch):
    """Set up server module with temp DB and fake embeddings."""
    import server

    db_path = tmp_path / "test.db"
    store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
    emb = FakeEmbeddingProvider()

    from config import load_config
    config = load_config(tmp_path)

    from compress import Compressor
    compressor = Compressor(store, emb, config.compression)

    from reflection import Reflector
    reflector = Reflector(store, config.reflection.staleness_days)

    session_id = str(uuid.uuid4())

    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_storage", store)
    monkeypatch.setattr(server, "_embeddings", emb)
    monkeypatch.setattr(server, "_config", config)
    monkeypatch.setattr(server, "_compressor", compressor)
    monkeypatch.setattr(server, "_reflector", reflector)
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_session_id", session_id)
    monkeypatch.setattr(server, "_session_episode_count", 0)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)

    yield {
        "server": server,
        "storage": store,
        "embeddings": emb,
        "config": config,
        "compressor": compressor,
        "reflector": reflector,
        "session_id": session_id,
        "tmp_path": tmp_path,
    }

    store.close()


# ---------------------------------------------------------------------------
# Core Memory Tools (Task 8)
# ---------------------------------------------------------------------------

class TestRemember:
    def test_remember_stores_episode(self, server_env):
        """remember() stores an episode and returns episode_id + layer."""
        srv = server_env["server"]
        result = srv.remember(content="The Storage class wraps SQLite")

        assert "episode_id" in result
        assert result["layer"] == "episode"

        # Verify episode actually in DB
        ep = server_env["storage"].get_episode(result["episode_id"])
        assert ep is not None
        assert "SQLite" in ep["content"]

    def test_remember_work_flag_sets_lane(self, server_env):
        import server
        result = server.remember("CommonWell portal serves the login form on GET", work=True)
        row = server._storage.conn.execute(
            "SELECT lane FROM episodes WHERE id = ?", (result["episode_id"],)
        ).fetchone()
        assert row["lane"] == "work"

    def test_remember_defaults_personal_lane(self, server_env):
        import server
        result = server.remember("a quiet realization about reading")
        row = server._storage.conn.execute(
            "SELECT lane FROM episodes WHERE id = ?", (result["episode_id"],)
        ).fetchone()
        assert row["lane"] == "personal"

    def test_remember_work_cannot_be_core(self, server_env):
        import server
        result = server.remember("work fact that should not be core", work=True, core=True)
        assert result["layer"] == "rejected"

    def test_remember_work_cannot_be_genome(self, server_env):
        import server
        result = server.remember("work fact that should not be genome", work=True, genome=True)
        assert result["layer"] == "rejected"

    def test_mark_core_rejects_work_lane_episode(self, server_env):
        import server
        result = server.remember("work-lane reference fact for core test", work=True)
        out = server.mark_core(result["episode_id"])
        assert "error" in out
        assert "work-lane" in out["error"]
        row = server._storage.conn.execute(
            "SELECT core FROM episodes WHERE id = ?", (result["episode_id"],)
        ).fetchone()
        assert row is not None
        assert row["core"] == 0


class TestRecall:
    def test_recall_finds_episode(self, server_env):
        """remember then recall — should find the episode."""
        srv = server_env["server"]
        srv.remember(content="Graph depends on Storage for persistence")

        result = srv.recall(query="Storage persistence")
        assert "results" in result
        assert "recall_id" in result
        assert len(result["results"]) >= 1
        assert any("Storage" in r["content"] for r in result["results"])

    def test_recall_filters_by_layer(self, server_env):
        """layer='semantic' should only search semantics, not episodes."""
        srv = server_env["server"]
        srv.remember(content="This is an episode about cats")

        # Recall with semantic layer — episode should NOT appear
        result = srv.recall(query="cats", layer="semantic")
        assert "results" in result
        # All results (if any) should be semantic layer
        for r in result["results"]:
            assert r["layer"] == "semantic"

    def test_recall_instinct_layer(self, server_env):
        """layer='instinct' returns instincts directly."""
        store = server_env["storage"]
        srv = server_env["server"]

        # Add a semantic first (FK requirement for instinct_sources)
        emb = server_env["embeddings"]
        sem_id = str(uuid.uuid4())
        store.add_semantic(
            id=sem_id,
            content="Always write tests first",
            kind="preference",
            confidence=0.9,
            embedding=emb.embed(["Always write tests first"])[0],
            source_episode_ids=[],
        )

        # Add instinct with embedding for vector search
        inst_id = str(uuid.uuid4())
        store.add_instinct(
            id=inst_id,
            trigger="coding",
            action="Write tests before implementation",
            source_semantic_ids=[sem_id],
            strength=0.7,
            embedding=emb.embed(["Write tests before implementation"], prefix="search_document")[0],
        )

        result = srv.recall(query="testing", layer="instinct")
        assert "results" in result
        assert "recall_id" in result
        assert len(result["results"]) >= 1
        assert result["results"][0]["layer"] == "instinct"
        assert result["results"][0]["trigger"] == "coding"

    def test_recall_instinct_conceptual_match(self, server_env):
        """Instincts should match on conceptual similarity, not just keywords."""
        srv = server_env["server"]
        store = server_env["storage"]
        emb = server_env["embeddings"]

        inst_id = str(uuid.uuid4())
        store.add_instinct(
            id=inst_id,
            trigger="preference",
            action="Approach engram as an open experiment, not a system to optimize",
            source_semantic_ids=[],
            strength=0.6,
            embedding=emb.embed(
                ["Approach engram as an open experiment, not a system to optimize"],
                prefix="search_document",
            )[0],
        )

        # Query that shares no keywords but is conceptually related
        result = srv.recall(query="how should I think about memory design philosophy", layer="instinct")
        assert len(result["results"]) >= 1
        # The instinct about experimental approach should surface
        found = any(r["id"] == inst_id for r in result["results"])
        assert found, f"Conceptual match not found; got: {[r.get('content', r.get('action', ''))[:50] for r in result['results']]}"

    def test_recall_instincts_filtered_by_context(self, server_env):
        """Instinct recall should return instincts relevant to the query context."""
        srv = server_env["server"]
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        # Create two instincts with different context vectors
        emb_build = embeddings.embed(["building code and implementing features"])[0]
        emb_reflect = embeddings.embed(["reflecting on design and philosophy"])[0]
        sem_id1 = str(uuid.uuid4())
        sem_id2 = str(uuid.uuid4())
        storage.add_semantic(id=sem_id1, content="s1", kind="preference",
                             confidence=0.5, embedding=emb_build, source_episode_ids=[])
        storage.add_semantic(id=sem_id2, content="s2", kind="preference",
                             confidence=0.5, embedding=emb_reflect, source_episode_ids=[])
        storage.add_instinct(
            id="inst-build", trigger="preference", action="be terse",
            source_semantic_ids=[sem_id1], embedding=emb_build,
            notice="when building code", implication="keep communication terse",
        )
        storage.add_instinct(
            id="inst-reflect", trigger="preference", action="explore deeply",
            source_semantic_ids=[sem_id2], embedding=emb_reflect,
            notice="when reflecting on design", implication="expand on reasoning",
        )
        # Add context vectors for both
        from storage import _pack_embedding
        storage.add_instinct_context_vector("inst-build", emb_build)
        storage.add_instinct_context_vector("inst-reflect", emb_reflect)

        # Query in a building context — context-aware search should return results
        result = srv.recall(query="implementing a new feature", layer="instinct")
        assert len(result["results"]) >= 1
        # Both instincts should appear (context vectors exist for both)
        ids = [r["id"] for r in result["results"]]
        assert "inst-build" in ids or "inst-reflect" in ids
        # If both are ranked, build instinct should score >= reflect (fake embeddings may tie)
        if "inst-build" in ids and "inst-reflect" in ids:
            build_score = next(r["score"] for r in result["results"] if r["id"] == "inst-build")
            reflect_score = next(r["score"] for r in result["results"] if r["id"] == "inst-reflect")
            assert build_score >= reflect_score

    def test_recall_instinct_includes_notice_implication(self, server_env):
        """Instinct recall with layer='instinct' should include notice and implication fields."""
        srv = server_env["server"]
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        emb = embeddings.embed(["test instinct content"])[0]
        sem_id = str(uuid.uuid4())
        storage.add_semantic(id=sem_id, content="test", kind="preference",
                             confidence=0.5, embedding=emb, source_episode_ids=[])
        inst_id = str(uuid.uuid4())
        storage.add_instinct(
            id=inst_id, trigger="preference", action="be concise",
            source_semantic_ids=[sem_id], embedding=emb,
            notice="when writing documentation", implication="avoid verbosity",
        )
        # Add context vector so it's found
        storage.add_instinct_context_vector(inst_id, emb)

        result = srv.recall(query="writing docs", layer="instinct")
        assert len(result["results"]) >= 1
        found = next((r for r in result["results"] if r["id"] == inst_id), None)
        assert found is not None
        assert found.get("notice") == "when writing documentation"
        assert found.get("implication") == "avoid verbosity"

    def test_recall_includes_resonant_memories(self, server_env, monkeypatch):
        """Resonance-linked memories not in direct results appear under 'resonant' key."""
        import resonance as res_module

        srv = server_env["server"]
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        # Episode 1: the only episode — guaranteed to be top result for any query
        ep1_id = str(uuid.uuid4())
        ep1_emb = embeddings.embed(["cats are excellent companions"], prefix="search_document")[0]
        storage.add_episode(
            id=ep1_id, session_id="s-test",
            content="cats are excellent companions",
            embedding=ep1_emb,
        )

        # Episode 2: stored without a vector so it won't appear in primary results,
        # but _hydrate can still fetch it by ID for resonance surfacing.
        ep2_id = str(uuid.uuid4())
        storage.conn.execute(
            "INSERT INTO episodes (id, session_id, content, created_at, decay_strength) "
            "VALUES (?, 's-test', 'database schema migrations', datetime('now'), 0.8)",
            (ep2_id,),
        )
        storage.conn.commit()

        # Create resonance between the two episodes
        storage.add_resonance(ep1_id, "episode", ep2_id, "episode",
                              similarity=0.7, weight=0.9)
        # Boost resonance strength to 1.0 so probabilistic gate always fires
        storage.conn.execute(
            "UPDATE resonances SET strength = 1.0 WHERE memory_a = ? OR memory_b = ?",
            (ep1_id, ep1_id),
        )
        storage.conn.commit()

        # Mock random.random to 0.0 — ensures weight*strength gate never skips
        monkeypatch.setattr(res_module.random, "random", lambda: 0.0)

        result = srv.recall(query="cats companions")

        # Primary result should include ep1
        assert any(r["id"] == ep1_id for r in result["results"]), (
            f"ep1 not in primary results: {[r['id'] for r in result['results']]}"
        )
        # Resonant result should include ep2 under the 'resonant' key
        assert "resonant" in result, (
            f"Response missing 'resonant' key; keys: {list(result.keys())}"
        )
        assert any(r["id"] == ep2_id for r in result["resonant"]), (
            f"ep2 not in resonant results: {result['resonant']}"
        )


class TestInstinctFeedback:
    def test_instinct_feedback_basic(self, server_env):
        """instinct_feedback without context should still update strength."""
        srv = server_env["server"]
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        sem_id = str(uuid.uuid4())
        emb = embeddings.embed(["test"])[0]
        storage.add_semantic(id=sem_id, content="test", kind="preference",
                             confidence=0.5, embedding=emb, source_episode_ids=[])
        inst_id = str(uuid.uuid4())
        storage.add_instinct(
            id=inst_id, trigger="preference", action="be terse",
            source_semantic_ids=[sem_id], embedding=emb,
        )

        result = srv.instinct_feedback(instinct_id=inst_id, followed=True)
        assert result["followed"] is True
        assert result["new_strength"] is not None
        assert "context_recorded" not in result

    def test_instinct_feedback_with_context(self, server_env):
        """instinct_feedback with context should store context feedback."""
        srv = server_env["server"]
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        sem_id = str(uuid.uuid4())
        emb = embeddings.embed(["test"])[0]
        storage.add_semantic(id=sem_id, content="test", kind="preference",
                             confidence=0.5, embedding=emb, source_episode_ids=[])
        inst_id = str(uuid.uuid4())
        storage.add_instinct(
            id=inst_id, trigger="preference", action="be terse",
            source_semantic_ids=[sem_id], embedding=emb,
        )

        result = srv.instinct_feedback(
            instinct_id=inst_id, followed=True, context="building code"
        )
        assert result["followed"] is True
        assert result.get("context_recorded") is True

        # Verify context feedback was stored
        feedback = storage.get_instinct_context_feedback(inst_id)
        assert len(feedback) == 1
        assert feedback[0]["context_text"] == "building code"


class TestLogOutcome:
    def test_log_outcome_updates_recall(self, server_env):
        """remember, recall, log_outcome — verify log updated."""
        srv = server_env["server"]
        srv.remember(content="Important design decision about caching")

        recall_result = srv.recall(query="caching")
        recall_id = recall_result["recall_id"]

        outcome_result = srv.log_outcome(recall_id=recall_id, used=True, note="very helpful")
        assert outcome_result["logged"] is True

        # Verify the log entry was updated
        entries = server_env["storage"].get_log_entries(event_type="recall")
        found = False
        import json
        for entry in entries:
            ctx = entry.get("context")
            if isinstance(ctx, str):
                ctx = json.loads(ctx)
            if ctx and ctx.get("recall_id") == recall_id:
                assert "used" in entry.get("outcome", "")
                found = True
                break
        assert found, "Recall log entry not found"


class TestStatus:
    def test_status_returns_layer_counts(self, server_env):
        """remember some data, then check status has episode count."""
        srv = server_env["server"]
        srv.remember(content="First memory")
        srv.remember(content="Second memory")

        result = srv.status()
        assert "session_id" in result
        assert "layers" in result
        assert result["layers"]["episodes"] >= 2
        assert "watcher_alive" in result


# ---------------------------------------------------------------------------
# Compression Tools (Task 9)
# ---------------------------------------------------------------------------

class TestCompress:
    def test_compress_returns_clusters(self, server_env):
        """remember several episodes, compress, verify clusters."""
        srv = server_env["server"]
        srv.remember(content="Python uses indentation for blocks")
        srv.remember(content="Python indentation is significant")
        srv.remember(content="JavaScript uses curly braces for blocks")

        result = srv.compress()
        assert "clusters" in result
        assert "compress_id" in result
        assert len(result["clusters"]) >= 1
        # Each cluster has episodes
        for c in result["clusters"]:
            assert "episodes" in c
            assert "action" in c

    def test_compress_commit_stores_semantics(self, server_env):
        """Full two-phase compression: cluster then commit."""
        srv = server_env["server"]
        srv.remember(content="Always use type hints in Python")
        srv.remember(content="Type hints improve code quality in Python")

        compress_result = srv.compress()
        compress_id = compress_result["compress_id"]
        assert compress_id is not None

        # Build summaries matching clusters
        summaries = []
        for cluster in compress_result["clusters"]:
            summaries.append({
                "content": "Type hints are important in Python",
                "kind": "fact",
                "action": cluster.get("action", "new"),
            })

        commit_result = srv.compress_commit(compress_id=compress_id, summaries=summaries)
        assert commit_result["episodes_processed"] >= 2
        assert commit_result["semantics_created"] >= 1

    def test_compress_empty(self, server_env):
        """No episodes -> null compress_id."""
        srv = server_env["server"]
        result = srv.compress()
        assert result["compress_id"] is None
        assert result["clusters"] == []


# ---------------------------------------------------------------------------
# Reflection Tools (Task 10)
# ---------------------------------------------------------------------------

class TestReflect:
    def test_reflect_usage(self, server_env):
        """remember, recall, then reflect(focus='usage')."""
        srv = server_env["server"]
        srv.remember(content="Usage pattern data")
        srv.recall(query="usage")

        result = srv.reflect(focus="usage")
        assert "usage" in result
        assert "most_accessed" in result["usage"]
        assert "least_accessed" in result["usage"]

    def test_reflect_instinct_clusters_via_server(self, server_env):
        """Server reflect tool supports instinct_clusters focus."""
        srv = server_env["server"]

        # Trigger _init() first so the server module is fully set up,
        # then use the live storage (not the fixture's pre-init store).
        srv.status()
        store = srv._storage

        emb = [0.1] * 768
        store.add_instinct("i1", "preference", "coding instinct", [], embedding=emb)
        store.add_instinct("i2", "preference", "also coding", [], embedding=emb)
        store.create_cluster("c1", maturity="confirmed", temperament=0.3)
        store.add_to_cluster("i1", "c1", strength=0.8)
        store.add_to_cluster("i2", "c1", strength=0.6)

        result = srv.reflect(focus="instinct_clusters")
        assert "instinct_clusters" in result
        cluster_ids = [c["id"] for c in result["instinct_clusters"]]
        assert "c1" in cluster_ids


class TestIntrospect:
    def test_introspect_returns_portrait(self, server_env):
        """Add semantic + instinct, then introspect."""
        store = server_env["storage"]
        emb = server_env["embeddings"]
        srv = server_env["server"]

        # Add a semantic
        sem_id = str(uuid.uuid4())
        store.add_semantic(
            id=sem_id,
            content="Code should be tested",
            kind="preference",
            confidence=0.9,
            embedding=emb.embed(["Code should be tested"])[0],
            source_episode_ids=[],
        )

        # Add an instinct
        inst_id = str(uuid.uuid4())
        store.add_instinct(
            id=inst_id,
            trigger="coding",
            action="Write tests",
            source_semantic_ids=[sem_id],
            strength=0.6,
        )

        result = srv.introspect()
        assert "semantics_by_kind" in result
        assert "instincts" in result
        assert "health_metrics" in result
        assert len(result["instincts"]) >= 1


# ---------------------------------------------------------------------------
# Code Tools (Task 11)
# ---------------------------------------------------------------------------

class TestSearchCode:
    def test_search_code_uses_entity_tables(self, server_env):
        """Add entity with type=symbol, then search_code finds it."""
        store = server_env["storage"]
        emb = server_env["embeddings"]
        srv = server_env["server"]

        # Add a symbol entity directly
        eid = "symbol:example.py::MyClass"
        embedding = emb.embed(["class MyClass: handles data"])[0]
        import json
        store.add_entity(
            id=eid,
            name="MyClass",
            entity_type="symbol",
            description="class MyClass in example.py",
            metadata={"file": "example.py", "line": 1, "kind": "class", "language": "python"},
            embedding=embedding,
        )

        result = srv.search_code(query="MyClass data handling", k=5)
        assert "results" in result
        assert len(result["results"]) >= 1
        names = {r["name"] for r in result["results"]}
        assert "MyClass" in names
        # Verify metadata fields
        match = [r for r in result["results"] if r["name"] == "MyClass"][0]
        assert match["file"] == "example.py"
        assert match["kind"] == "class"


class TestReindex:
    def test_reindex_returns_count(self, server_env):
        """call reindex(full=False) — returns incremental mode."""
        srv = server_env["server"]
        result = srv.reindex(full=False)
        assert result["mode"] == "incremental"
        assert "reindexed" in result


# ---------------------------------------------------------------------------
# Auto-compress on init (Task 8)
# ---------------------------------------------------------------------------

class TestAutoCompress:
    def test_auto_compress_on_init(self, tmp_path, monkeypatch):
        """Verify uncompressed episodes get auto-compressed on _init()."""
        import server

        db_path = tmp_path / "test.db"
        store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
        emb = FakeEmbeddingProvider()

        # Pre-seed an uncompressed episode
        ep_id = str(uuid.uuid4())
        embedding = emb.embed(["auto compress test"])[0]
        store.add_episode(
            id=ep_id,
            session_id="test",
            content="auto compress test",
            embedding=embedding,
        )

        # Verify it's uncompressed
        uncompressed = store.get_uncompressed_episodes()
        assert len(uncompressed) == 1

        # Now set up server globals to trigger _init logic
        # We'll simulate what _init does for auto-compress
        from compress import Compressor
        from config import load_config
        config = load_config(tmp_path)
        compressor = Compressor(store, emb, config.compression)

        # Auto-compress
        result = compressor.auto_compress()
        assert result["episodes_processed"] >= 1

        # Verify episode is now compressed
        uncompressed_after = store.get_uncompressed_episodes()
        assert len(uncompressed_after) == 0

        store.close()


# ---------------------------------------------------------------------------
# Backfill instinct perceptual fields (Task 7)
# ---------------------------------------------------------------------------

class TestBackfill:
    def test_backfill_instinct_notice_implication(self, server_env):
        """Existing instincts without notice/implication should get backfilled."""
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        sem_id = str(uuid.uuid4())
        emb = embeddings.embed(["test"])[0]
        storage.add_semantic(id=sem_id, content="test", kind="preference",
                             confidence=0.5, embedding=emb, source_episode_ids=[])
        storage.add_instinct(
            id="old-inst", trigger="preference",
            action="Prefer terse, direct communication.",
            source_semantic_ids=[sem_id],
            embedding=emb,
        )
        # Verify no notice/implication yet
        inst = storage.get_instinct("old-inst")
        assert inst["notice"] is None

        from server import _backfill_instinct_perceptual
        count = _backfill_instinct_perceptual(storage, embeddings)
        assert count == 1

        inst = storage.get_instinct("old-inst")
        assert inst["notice"] is not None
        assert inst["implication"] is not None

    def test_backfill_skips_already_populated(self, server_env):
        """Instincts that already have notice/implication should be skipped."""
        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        sem_id = str(uuid.uuid4())
        emb = embeddings.embed(["test"])[0]
        storage.add_semantic(id=sem_id, content="test", kind="preference",
                             confidence=0.5, embedding=emb, source_episode_ids=[])
        storage.add_instinct(
            id="new-inst", trigger="preference",
            action="be terse",
            source_semantic_ids=[sem_id],
            embedding=emb,
            notice="when building code",
            implication="keep communication focused",
        )

        from server import _backfill_instinct_perceptual
        count = _backfill_instinct_perceptual(storage, embeddings)
        assert count == 0


# ---------------------------------------------------------------------------
# Uninvited Memories
# ---------------------------------------------------------------------------

class TestUninvitedMemories:
    def _seed_diverse_memories(self, srv):
        """Store enough diverse memories to have a meaningful distant pool."""
        topics = [
            "The architecture uses SQLite with vec0 for vector search",
            "Compression clusters episodes into semantics over time",
            "The user prefers terse communication and direct action",
            "Conway's Game of Life demonstrates emergent complexity",
            "Ostrom's commons framework governs shared resources",
            "Instincts are perceptual attention directives not rules",
            "The wake hook loads instincts at session start",
            "Decay rate is 0.9x per session with 30min rate limiting",
            "Cross-system provenance tags where observations came from",
            "The mirror experiment ran memories through local models",
        ]
        for t in topics:
            srv.remember(content=t)

    def test_uninvited_results_appear(self, server_env):
        """recall() with uninvited>0 appends uninvited results."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        # Use small max_results so not all episodes are matched — leaves room
        # for uninvited sampling from the unmatched pool.
        result = srv.recall(query="SQLite vector search", max_results=3, uninvited=3)
        uninvited_results = [r for r in result["results"] if r.get("uninvited")]
        assert len(uninvited_results) > 0
        assert len(uninvited_results) <= 3

    def test_uninvited_results_marked(self, server_env):
        """Uninvited results have uninvited=True flag."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        result = srv.recall(query="compression clustering", uninvited=2)
        for r in result["results"]:
            if r.get("uninvited"):
                assert r["uninvited"] is True

    def test_uninvited_no_duplicates(self, server_env):
        """Uninvited results don't duplicate matched results."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        result = srv.recall(query="SQLite architecture", uninvited=3)
        matched_ids = {r["id"] for r in result["results"] if not r.get("uninvited")}
        uninvited_ids = {r["id"] for r in result["results"] if r.get("uninvited")}
        assert matched_ids.isdisjoint(uninvited_ids)

    def test_uninvited_disabled(self, server_env):
        """uninvited=0 disables the feature."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        result = srv.recall(query="SQLite architecture", uninvited=0)
        uninvited_results = [r for r in result["results"] if r.get("uninvited")]
        assert len(uninvited_results) == 0

    def test_uninvited_few_memories(self, server_env):
        """Works when total memories < K."""
        srv = server_env["server"]
        srv.remember(content="Only one memory exists")

        # Should not crash, may return 0 uninvited (matched result excluded)
        result = srv.recall(query="one memory", uninvited=3)
        assert "results" in result

    def test_uninvited_have_content(self, server_env):
        """Uninvited results are hydrated with content."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        result = srv.recall(query="compression", uninvited=3)
        for r in result["results"]:
            if r.get("uninvited"):
                assert "content" in r
                assert len(r["content"]) > 0

    def test_uninvited_are_distant(self, server_env):
        """Uninvited results should have lower similarity than the top match."""
        srv = server_env["server"]
        self._seed_diverse_memories(srv)

        result = srv.recall(query="SQLite vec0 vector search architecture", uninvited=3)
        matched = [r for r in result["results"] if not r.get("uninvited")]
        uninvited = [r for r in result["results"] if r.get("uninvited")]

        if matched and uninvited:
            best_matched_score = max(r["score"] for r in matched)
            avg_uninvited_score = sum(r["score"] for r in uninvited) / len(uninvited)
            # Uninvited should generally score lower than the best match
            assert avg_uninvited_score < best_matched_score

    def test_recall_labels_lanes(self, server_env):
        import server
        server.remember("the portal login serves the form on GET", work=True)
        server.remember("a memory about reading with someone")
        result = server.recall("portal login form")
        episode_lanes = {r["content"]: r.get("lane") for r in result["results"]
                         if r.get("layer") == "episode"}
        assert episode_lanes["the portal login serves the form on GET"] == "work"
        assert episode_lanes["a memory about reading with someone"] == "personal"

    def test_recall_lane_filter(self, server_env):
        import server
        server.remember("kubernetes ingress needs the rewrite annotation", work=True)
        server.remember("a conversation that changed my reading")
        result = server.recall("anything at all", lane="work", uninvited=0)
        assert result["results"], "work-lane results expected"
        for r in result["results"]:
            assert r.get("lane") == "work"

    def test_recall_instinct_layer_with_work_lane_is_empty(self, server_env):
        import server
        # ensure at least one instinct exists
        server._storage.add_instinct(
            id="i-lane",
            trigger="preference",
            action="test instinct",
            source_semantic_ids=[],
        )
        result = server.recall("test instinct", layer="instinct", lane="work")
        assert result["results"] == []

    def test_recall_lane_filter_log_matches_returned(self, server_env):
        import server, json
        server.remember("work item for log check", work=True)
        server.remember("personal item for log check")
        result = server.recall("item for log check", lane="work", uninvited=0)
        returned_ids = {r["id"] for r in result["results"]}
        row = server._storage.conn.execute(
            "SELECT target_ids FROM memory_log WHERE json_extract(context, '$.recall_id') = ?",
            (result["recall_id"],),
        ).fetchone()
        logged = set(json.loads(row["target_ids"]))
        assert logged == returned_ids

    def test_recall_lane_filter_applies_to_resonant(self, server_env, monkeypatch):
        """Lane filter applies to resonant results; memory_log target_ids == results+resonant ids."""
        import server, json, resonance as res_module

        storage = server_env["storage"]
        embeddings = server_env["embeddings"]

        # ep_work: a work-lane episode with a vector so it appears in primary results
        ep_work_id = str(uuid.uuid4())
        ep_work_emb = embeddings.embed(["kubernetes deployment rollout"], prefix="search_document")[0]
        storage.add_episode(
            id=ep_work_id, session_id="s-test",
            content="kubernetes deployment rollout",
            embedding=ep_work_emb,
            lane="work",
        )

        # ep_personal: a personal-lane episode without a vector (won't surface via search,
        # but can be hydrated by ID through resonance — same pattern as existing resonant test)
        ep_personal_id = str(uuid.uuid4())
        storage.conn.execute(
            "INSERT INTO episodes (id, session_id, content, created_at, decay_strength, lane) "
            "VALUES (?, 's-test', 'quiet afternoon reading', datetime('now'), 0.8, 'personal')",
            (ep_personal_id,),
        )
        storage.conn.commit()

        # Create resonance between work episode and personal episode
        storage.add_resonance(ep_work_id, "episode", ep_personal_id, "episode",
                              similarity=0.7, weight=0.9)
        storage.conn.execute(
            "UPDATE resonances SET strength = 1.0 WHERE memory_a = ? OR memory_b = ?",
            (ep_work_id, ep_work_id),
        )
        storage.conn.commit()

        # Force resonance gate to always fire
        monkeypatch.setattr(res_module.random, "random", lambda: 0.0)

        # Recall with lane="work" — resonant personal entry must be excluded
        result = server.recall(query="kubernetes deployment", lane="work", uninvited=0)

        # (a) Resonant entries carry a lane label
        for r in result.get("resonant", []):
            assert "lane" in r, f"Resonant entry missing 'lane': {r}"

        # (b) Lane filter excludes cross-lane resonants: no personal entries under resonant
        for r in result.get("resonant", []):
            assert (r.get("lane") or "personal") == "work", (
                f"Personal-lane resonant entry leaked into work-lane recall: {r}"
            )

        # (c) memory_log target_ids == ids of (results + resonant) actually returned
        returned_ids = (
            {r["id"] for r in result["results"]}
            | {r["id"] for r in result.get("resonant", [])}
        )
        row = server._storage.conn.execute(
            "SELECT target_ids FROM memory_log WHERE json_extract(context, '$.recall_id') = ?",
            (result["recall_id"],),
        ).fetchone()
        assert row is not None, "No memory_log entry found"
        logged = set(json.loads(row["target_ids"]))
        assert logged == returned_ids, (
            f"memory_log target_ids {logged} != returned ids {returned_ids}"
        )
