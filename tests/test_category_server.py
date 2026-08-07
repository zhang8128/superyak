"""Behavioral integration tests for evolving categories at the recall boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
import uuid

import pytest

from category_compile import CompiledCategory, CompiledCell
import category_evolution
from storage import Storage


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


class FakeEmbeddingProvider:
    def dimension(self) -> int:
        return 768

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        vectors = []
        for text in texts:
            seed = sum(text.encode("utf-8")) or 1
            vector = [float((seed + index) % 17) for index in range(768)]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


@pytest.fixture
def category_server_env(tmp_path, monkeypatch):
    import server

    store = Storage(str(tmp_path / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    embeddings = FakeEmbeddingProvider()
    from config import load_config
    from compress import Compressor
    from reflection import Reflector

    config = load_config(tmp_path)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_storage", store)
    monkeypatch.setattr(server, "_embeddings", embeddings)
    monkeypatch.setattr(server, "_config", config)
    monkeypatch.setattr(server, "_compressor", Compressor(store, embeddings, config.compression))
    monkeypatch.setattr(server, "_reflector", Reflector(store))
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_session_id", str(uuid.uuid4()))
    monkeypatch.setattr(server, "_category_store", None)
    monkeypatch.setattr(server, "_category_observer", None, raising=False)
    monkeypatch.setattr(server, "_knowledge_graph", None)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server, "_form_resonances", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_surface_resonances", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(server, "_has_active_residue", lambda: False)

    yield server, config
    store.close()


class RecordingObserver:
    def __init__(self, compiled: CompiledCategory | None = None, observe_error=None):
        self.compiled = compiled or CompiledCategory("", None, (), 0, 0, False, False)
        self.observe_error = observe_error
        self.observed = []
        self.adjusted = 0

    def observe_recall(self, query, result_ids, *, source, observed_at):
        if self.observe_error is not None:
            raise self.observe_error
        self.observed.append((query, tuple(result_ids), source, observed_at))

    def compile_for_recall(self, seed_ids, base_tokens=0):
        return self.compiled

    def adjust_results(self, results, compiled, influence=0.10):
        self.adjusted += 1
        return category_evolution.CategoryObserver.adjust_results(results, compiled, influence)


def _fixed_server_clock(monkeypatch, server):
    real_datetime = datetime

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = real_datetime(2030, 1, 1, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(server, "datetime", FixedDateTime)


def test_shadow_observer_is_byte_for_byte_inert_and_has_no_response_field(
    category_server_env, monkeypatch
):
    """Catches shadow diagnostics changing recall fields, order, or scores."""
    server, config = category_server_env
    _fixed_server_clock(monkeypatch, server)
    server.remember("deterministic category shadow memory")
    baseline = server.recall("category shadow", uninvited=0)

    config.category_evolution.enabled = True
    config.category_evolution.shadow = True
    config.category_evolution.influence_recall = False
    observer = RecordingObserver()
    monkeypatch.setattr(server, "_category_observer", observer)

    shadow = server.recall("category shadow", uninvited=0)

    assert shadow["results"] == baseline["results"]
    assert set(shadow) == set(baseline)
    assert "category" not in shadow
    assert observer.observed and observer.adjusted == 0


def test_observer_database_error_is_non_fatal_and_content_safe_in_logs(
    category_server_env, monkeypatch, caplog
):
    """Catches observer failures escaping recall or logging query/memory content."""
    server, config = category_server_env
    _fixed_server_clock(monkeypatch, server)
    server.remember("private-memory-marker")
    config.category_evolution.enabled = True
    config.category_evolution.shadow = True
    monkeypatch.setattr(
        server,
        "_category_observer",
        RecordingObserver(observe_error=sqlite3.DatabaseError("private-query-marker")),
    )

    result = server.recall("private-query-marker", uninvited=0)

    assert result["results"]
    category_logs = "\n".join(
        record.getMessage() for record in caplog.records if "Category observer" in record.getMessage()
    )
    assert "DatabaseError" in category_logs
    assert "private-query-marker" not in category_logs
    assert "private-memory-marker" not in category_logs


def test_live_influence_blends_existing_results_without_injection_or_commentary(
    category_server_env, monkeypatch
):
    """Catches influence changing membership/payload or using the wrong blend."""
    server, config = category_server_env
    _fixed_server_clock(monkeypatch, server)
    server.remember("alpha category result")
    server.remember("beta category result")
    baseline = server.recall("category result", uninvited=0)["results"]
    category_scores = {baseline[0]["id"]: 0.0, baseline[1]["id"]: 1.0}
    cells = tuple(
        CompiledCell(
            category_evolution.CategoryObserver.proxy_id(result_id),
            "proxy",
            0,
            category_score,
            {},
            0,
            1,
        )
        for result_id, category_score in category_scores.items()
    )
    observer = RecordingObserver(CompiledCategory("epoch", None, cells, 2, 2, False, False))
    config.category_evolution.enabled = True
    config.category_evolution.shadow = False
    config.category_evolution.influence_recall = True
    monkeypatch.setattr(server, "_category_observer", observer)

    influenced = server.recall("category result", uninvited=0)["results"]

    assert {item["id"] for item in influenced} == {item["id"] for item in baseline}
    expected = {
        item["id"]: 0.90 * item["score"] + 0.10 * category_scores[item["id"]]
        for item in baseline
    }
    assert {item["id"]: item["score"] for item in influenced} == expected
    assert all(set(item) == set(next(base for base in baseline if base["id"] == item["id"])) for item in influenced)
    assert all("commentary" not in item for item in influenced)
    assert observer.adjusted == 1


def test_observation_and_outcome_retries_are_idempotent_without_committing_epochs(tmp_path):
    """Catches retry duplication or structural consolidation on request paths."""
    database = tmp_path / "categories_v2.db"
    observer = category_evolution.CategoryObserver(
        database, shadow=True, influence_recall=False, auto_commit=False
    )
    observed_at = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    try:
        observer.observe_recall(
            "Normalize sparse context terms",
            ["memory-b", "memory-a"],
            source="/workspace/project",
            observed_at=observed_at,
        )
        observer.observe_recall(
            "Normalize sparse context terms",
            ["memory-b", "memory-a"],
            source="/workspace/project",
            observed_at=observed_at,
        )
        observer.observe_outcome("recall-1", True, "helpful")
        observer.observe_outcome("recall-1", True, "helpful")

        connection = observer.store.connection
        kinds = {
            row[0]: row[1]
            for row in connection.execute("SELECT kind, COUNT(*) FROM cat_events GROUP BY kind")
        }
        assert kinds == {"context_boundary": 1, "proxy_observed": 2, "recall_observed": 1, "recall_outcome": 1}
        assert connection.execute("SELECT COUNT(*) FROM cat_cells WHERE dimension=0").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM cat_epochs").fetchone()[0] == 0
    finally:
        observer.close()


def test_observer_report_retains_failure_type_without_failure_text(tmp_path, monkeypatch):
    """Catches non-fatal request errors disappearing from later diagnostics."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    original_append_event = observer.store.append_event

    def fail(*_args, **_kwargs):
        raise sqlite3.DatabaseError("private observation details")

    monkeypatch.setattr(observer.store, "append_event", fail)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            observer.observe_recall(
                "private query",
                ["private-memory"],
                source="/private/source",
                observed_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
            )
        monkeypatch.setattr(observer.store, "append_event", original_append_event)
        report = observer.report()
        assert report["last_error"] == "DatabaseError"
        assert "private observation details" not in str(report)
    finally:
        observer.close()


def test_adjust_results_preserves_invalid_or_missing_scores_and_breaks_ties_deterministically():
    """Catches NaN propagation, result loss, or unstable equal-score ordering."""
    results = [
        {"id": "b", "content": "B", "score": 0.5},
        {"id": "a", "content": "A", "score": 0.5},
        {"id": "missing", "content": "M"},
        {"id": "nan", "content": "N", "score": float("nan")},
    ]
    compiled = CompiledCategory(
        "epoch",
        None,
        (
            CompiledCell(category_evolution.CategoryObserver.proxy_id("a"), "", 0, 0.5, {}, 0, 1),
            CompiledCell(category_evolution.CategoryObserver.proxy_id("b"), "", 0, 0.5, {}, 0, 1),
            CompiledCell(category_evolution.CategoryObserver.proxy_id("missing"), "", 0, 1.0, {}, 0, 1),
            CompiledCell(category_evolution.CategoryObserver.proxy_id("nan"), "", 0, 1.0, {}, 0, 1),
        ),
        4,
        4,
        False,
        False,
    )

    adjusted = category_evolution.CategoryObserver.adjust_results(results, compiled)

    assert [item["id"] for item in adjusted] == ["a", "b", "missing", "nan"]
    assert adjusted[2] == results[2]
    assert math.isnan(adjusted[3]["score"])
    assert results[0]["score"] == 0.5
