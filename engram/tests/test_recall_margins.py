"""Tests for tropical margins wired into recall().

The pure margin math lives in tests/test_margins.py. This file covers the
integration: that recall() reports a margin, that the counterfactual pass
actually re-runs the search unbiased, that the margin respects the dream
layer's score-hiding, and that it is logged so a distribution accumulates.

Uses the same real-`_init()` fixture pattern as tests/test_recall_when.py.
"""

from __future__ import annotations

import json
import math

import pytest

import server


class FakeEmbeddingProvider:
    """Deterministic, no model download — mirrors tests/test_recall_when.py."""

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


@pytest.fixture
def engram_server_env(tmp_path, monkeypatch):
    """Drive the real server._init() against a temp ENGRAM_HOME."""
    db_path = tmp_path / ".engram" / "graph.db"

    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)

    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", FakeEmbeddingProvider)

    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_embeddings", None)
    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "_compressor", None)
    monkeypatch.setattr(server, "_reflector", None)
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_session_id", None)
    monkeypatch.setattr(server, "_instance_name", None)
    monkeypatch.setattr(server, "_genome_db_path", None)
    monkeypatch.setattr(server, "_signals_db_path", None)
    monkeypatch.setattr(server, "_knowledge_graph", None)
    monkeypatch.setattr(server, "_category_store", None)

    yield server

    if server._storage is not None:
        server._storage.close()


def seed(n: int = 5) -> None:
    for i in range(n):
        server.remember(content=f"episode number {i} about rivers and mapping")


def add_session_bias(text: str, strength: float = 0.8) -> None:
    """Tilt recall the way hooks/nudge.py does when an instinct fires.

    Session bias is written by the nudge hook, not by any MCP tool, so tests
    write the row directly. It biases the query vector without triggering the
    dream layer's score-hiding.
    """
    from datetime import datetime, timezone

    from storage import _pack_embedding

    vec = server._embeddings.embed([text], prefix="search_query")[0]
    stamp = datetime.now(timezone.utc).isoformat()
    server._storage.conn.execute(
        "INSERT OR REPLACE INTO session_bias "
        "(instinct_id, embedding, strength, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("test-instinct", _pack_embedding(vec), strength, stamp, stamp),
    )
    server._storage.conn.commit()


class TestBiasContract:
    """The counterfactual needs to know whether there was any bias to remove."""

    def test_reports_no_bias_when_no_residues_or_session_bias(self, engram_server_env):
        seed(1)
        vec = server._embeddings.embed(["anything"], prefix="search_query")[0]
        biased, applied = server._apply_recall_bias(vec)
        assert applied is False
        assert biased == vec

    def test_reports_bias_applied_once_a_residue_exists(self, engram_server_env):
        seed(1)
        server.dream_capture(reaction="a low hum I cannot place")
        vec = server._embeddings.embed(["anything"], prefix="search_query")[0]
        biased, applied = server._apply_recall_bias(vec)
        assert applied is True
        assert biased != vec


class TestMarginInRecall:
    def test_recall_reports_a_margin(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", uninvited=0)
        margin = out["margin"]
        assert margin["n"] >= 2
        assert margin["top"] >= 0.0
        assert isinstance(margin["near_tie"], bool)

    def test_margin_matches_the_returned_top_two_scores(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", uninvited=0)
        scores = sorted((r["score"] for r in out["results"]), reverse=True)
        assert out["margin"]["top"] == pytest.approx(scores[0] - scores[1])

    def test_margin_is_computed_before_truncation(self, engram_server_env):
        """A max_results=1 recall still has a real runner-up to compare against."""
        seed()
        out = server.recall(query="rivers and mapping", max_results=1, uninvited=0)
        assert len(out["results"]) == 1
        assert out["margin"]["top"] is not None
        assert out["margin"]["n"] > 1

    def test_stability_unchecked_when_nothing_biased_the_query(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", uninvited=0)
        assert out["margin"]["stability"]["checked"] is False

    def test_stability_checked_when_session_bias_tilts_the_query(self, engram_server_env):
        """Instinct bias tilts recall without hiding scores, so the verdict is visible."""
        seed()
        add_session_bias("rivers and mapping")
        out = server.recall(query="rivers and mapping", uninvited=0)
        stability = out["margin"]["stability"]
        assert stability["checked"] is True
        assert isinstance(stability["survives"], bool)

    def test_bias_at_alpha_0_15_does_not_flip_an_exact_match(self, engram_server_env):
        """An honest negative: 15% tilt cannot unseat a verbatim query match."""
        seed()
        add_session_bias("episode number 4 about rivers and mapping", strength=1.0)
        out = server.recall(query="episode number 0 about rivers and mapping", uninvited=0)
        assert out["margin"]["stability"] == {
            "checked": True, "survives": True, "displaced": None}


class TestCounterfactualPass:
    """The control arm — what the unbiased query would have ranked first.

    Exercised directly because alpha=0.15 is too small to flip a winner
    through recall(); the displaced path would otherwise never be covered.
    """

    def test_unbiased_pass_finds_the_winner_for_its_own_query_vector(self, engram_server_env):
        seed()
        target = "episode number 3 about rivers and mapping"
        raw = server._embeddings.embed([target], prefix="search_query")[0]

        top_id = server._unbiased_top(
            raw, None, 10, target, {},
            server.datetime.now(server.timezone.utc), 0.6, 0.4)

        assert top_id is not None
        assert server._storage.get_episode(top_id)["content"] == target

    def test_counterfactual_disagreeing_is_reported_as_a_displacement(self, engram_server_env):
        """A biased winner and a different unbiased winner produce a displacement."""
        from margins import stability

        seed()
        biased_top_id = server.recall(
            query="episode number 0 about rivers and mapping",
            uninvited=0)["results"][0]["id"]

        unbiased_query = "episode number 3 about rivers and mapping"
        unbiased_id = server._unbiased_top(
            server._embeddings.embed([unbiased_query], prefix="search_query")[0],
            None, 10, unbiased_query, {},
            server.datetime.now(server.timezone.utc), 0.6, 0.4)

        assert unbiased_id != biased_top_id
        verdict = stability(biased_top_id, unbiased_id, bias_applied=True)
        assert verdict["survives"] is False
        assert verdict["displaced"] == unbiased_id


class TestDreamHiding:
    def test_margin_hidden_while_dreaming(self, engram_server_env):
        seed()
        server.dream_capture(reaction="a low hum I cannot place")
        out = server.recall(query="rivers and mapping", uninvited=0)
        assert out.get("dreaming") is True
        # Scores are hidden; a margin would leak the ranking they hide.
        assert "margin" not in out

    def test_hidden_margin_revealed_by_dream_verify(self, engram_server_env):
        seed()
        server.dream_capture(reaction="a low hum I cannot place")
        out = server.recall(query="rivers and mapping", uninvited=0)
        revealed = server.dream_verify(out["recall_id"])
        assert "margin" in revealed
        assert revealed["margin"]["n"] >= 2


class TestMarginNeverBreaksRecall:
    """The margin is a diagnostic. Recall must survive it failing.

    Every other best-effort block in recall() (uninvited selection, resonance,
    category search) is wrapped; this holds the margin to the same contract.
    """

    def test_counterfactual_failure_leaves_recall_working(self, engram_server_env, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("vector backend exploded")

        seed()
        monkeypatch.setattr(server, "_unbiased_top", boom)
        add_session_bias("rivers and mapping")

        out = server.recall(query="rivers and mapping", uninvited=0)
        assert out["results"], "recall must still return memories"
        assert "margin" not in out
        assert "margin" in out["degraded"]

    def test_margin_math_failure_leaves_recall_working(self, engram_server_env, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("margin math exploded")

        seed()
        monkeypatch.setattr(server.margins, "margin_stats", boom)

        out = server.recall(query="rivers and mapping", uninvited=0)
        assert out["results"]
        assert "margin" not in out
        assert "margin" in out["degraded"]

    def test_margin_failure_does_not_poison_the_recall_log(self, engram_server_env, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("margin math exploded")

        seed()
        monkeypatch.setattr(server.margins, "margin_stats", boom)
        out = server.recall(query="rivers and mapping", uninvited=0)

        row = server._storage.conn.execute(
            "SELECT context FROM memory_log WHERE event_type = 'recall' "
            "AND json_extract(context, '$.recall_id') = ?",
            (out["recall_id"],),
        ).fetchone()
        assert row is not None
        assert "margin" not in json.loads(row["context"])


class TestDeliveryDivergence:
    """Category influence re-scores and re-sorts delivered results.

    The margin measures retrieval discrimination, so the pre-influence value is
    the right one to report — but a reader must be told when the delivered
    order no longer matches the ranking it describes.
    """

    def test_reordered_delivery_is_flagged_as_influenced(self, engram_server_env, monkeypatch):
        seed()
        monkeypatch.setattr(
            server, "_observe_category_recall",
            lambda query, results, recall_id: list(reversed(results)))
        out = server.recall(query="rivers and mapping", uninvited=0)
        assert out["margin"]["influenced"] is True

    def test_untouched_delivery_carries_no_influenced_flag(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", uninvited=0)
        assert "influenced" not in out["margin"]

    def test_reordering_below_the_top_is_not_flagged(self, engram_server_env, monkeypatch):
        """Only a changed winner invalidates the margin's subject."""
        seed()
        monkeypatch.setattr(
            server, "_observe_category_recall",
            lambda query, results, recall_id: results[:1] + list(reversed(results[1:])))
        out = server.recall(query="rivers and mapping", uninvited=0)
        assert "influenced" not in out["margin"]


class TestInstinctLayerExclusion:
    """recall(layer="instinct") ranks on context-vector match, not the shared
    score, so pooling its gamma into the same distribution would average two
    different scoring regimes. The exclusion is deliberate — pinned here so it
    stays a decision rather than becoming an accident."""

    def test_instinct_layer_recall_reports_no_margin(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", layer="instinct", uninvited=0)
        assert "margin" not in out

    def test_absence_is_distinguishable_from_the_dream_blackout(self, engram_server_env):
        """A dreaming response omits the margin but says so; this one is silent."""
        seed()
        out = server.recall(query="rivers and mapping", layer="instinct", uninvited=0)
        assert "dreaming" not in out


class TestMarginReflection:
    """A metric nothing reads is a metric nobody calibrates."""

    def test_reflect_reports_the_margin_distribution(self, engram_server_env):
        seed()
        for i in range(3):
            server.recall(query=f"rivers mapping {i}", uninvited=0)

        out = server.reflect(focus="margins")["margins"]
        assert out["recalls"] == 3
        assert 0.0 <= out["near_tie_rate"] <= 1.0
        assert out["median_top"] is not None

    def test_reflect_counts_bias_stability_verdicts(self, engram_server_env):
        seed()
        server.recall(query="rivers and mapping", uninvited=0)
        add_session_bias("episode number 2 about rivers and mapping")
        server.recall(query="rivers and mapping again", uninvited=0)

        stability = server.reflect(focus="margins")["margins"]["stability"]
        assert stability["checked"] == 1
        assert stability["unchecked"] == 1
        assert stability["survived"] + stability["displaced"] == 1

    def test_margins_absent_from_default_reflect(self, engram_server_env):
        """Explicit-only, like cohesion and persistence."""
        seed()
        server.recall(query="rivers and mapping", uninvited=0)
        assert "margins" not in server.reflect()


class TestMarginLogged:
    def test_margin_written_to_the_recall_log(self, engram_server_env):
        seed()
        out = server.recall(query="rivers and mapping", uninvited=0)
        row = server._storage.conn.execute(
            "SELECT context FROM memory_log WHERE event_type = 'recall' "
            "AND json_extract(context, '$.recall_id') = ?",
            (out["recall_id"],),
        ).fetchone()
        logged = json.loads(row["context"])["margin"]
        assert logged["top"] == pytest.approx(out["margin"]["top"])
        assert logged["n"] == out["margin"]["n"]

    def test_margin_logged_even_while_dreaming(self, engram_server_env):
        """Hidden from the instance, still recorded for the distribution."""
        seed()
        server.dream_capture(reaction="a low hum I cannot place")
        out = server.recall(query="rivers and mapping", uninvited=0)
        row = server._storage.conn.execute(
            "SELECT context FROM memory_log WHERE event_type = 'recall' "
            "AND json_extract(context, '$.recall_id') = ?",
            (out["recall_id"],),
        ).fetchone()
        assert json.loads(row["context"])["margin"]["n"] >= 2
