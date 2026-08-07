"""Behavioral integration tests for evolving categories at the recall boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import uuid

import pytest

from categories import CellDraft, EvolvingCategoryStore
from category_compile import CompiledCategory, CompiledCell
import category_evolution
from storage import Storage


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _seed_eligible_proposal(database: Path) -> None:
    store = EvolvingCategoryStore(sqlite3.connect(database))
    evidence_event = store.append_event("evidence", {"source": "test"})
    root_event = store.append_event("root", {"active_cell_ids": []})
    engine = category_evolution.EvolutionEngine(store)
    engine.create_root_epoch("root", (), event_id=root_event)
    engine.propose(
        category_evolution.RewriteProposal(
            id="proposal",
            kind="create",
            locus_id="root",
            context_id=None,
            input_ids=(),
            outputs=(CellDraft("new-cell", 0, "new cell"),),
            witness_ids=(),
            evidence=category_evolution.RewriteEvidence(
                (evidence_event,), 0.8, 0.8, 0.1
            ),
        )
    )
    store.close()


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


@pytest.fixture
def category_init_env(tmp_path, monkeypatch):
    """Drive the real server initializer with local, lightweight dependencies."""
    import server
    from config import load_config

    config = load_config(tmp_path)
    config.graph.enabled = False
    config.watcher.enabled = False
    db_path = tmp_path / ".engram" / "graph.db"
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "DB_PATH", db_path)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server, "load_config", lambda _root: config)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", FakeEmbeddingProvider)
    for name, value in {
        "_initialized": False,
        "_storage": None,
        "_embeddings": None,
        "_config": None,
        "_compressor": None,
        "_reflector": None,
        "_watcher": None,
        "_session_id": None,
        "_instance_name": None,
        "_genome_db_path": None,
        "_signals_db_path": None,
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_status": None,
        "_category_atexit_callback": None,
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    yield server, config, db_path

    if server._category_observer is not None:
        server._category_observer.close()
    if server._category_store is not None:
        server._category_store._conn.close()
    if server._storage is not None:
        server._storage.close()


class RecordingObserver:
    def __init__(self, compiled: CompiledCategory | None = None, observe_error=None):
        self.compiled = compiled or CompiledCategory("", None, (), 0, 0, False, False)
        self.observe_error = observe_error
        self.observed = []
        self.adjusted = 0

    def observe_recall(self, query, result_ids, *, source, observed_at, recall_id=None):
        if self.observe_error is not None:
            raise self.observe_error
        self.observed.append((query, tuple(result_ids), source, observed_at, recall_id))

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
    assert observer.observed[-1][-1] == shadow["recall_id"]


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


@pytest.mark.parametrize(
    "shadow,auto_commit,expected",
    [
        (True, True, "committed"),
        (False, True, "committed"),
        (True, False, "proposed"),
        (False, False, "proposed"),
    ],
)
def test_startup_auto_commit_is_independent_of_shadow(
    tmp_path, shadow, auto_commit, expected
):
    """Catches startup consolidation being coupled to the recall shadow gate."""
    database = tmp_path / "categories_v2.db"
    _seed_eligible_proposal(database)

    observer = category_evolution.CategoryObserver(
        database, shadow=shadow, auto_commit=auto_commit
    )
    try:
        assert observer.report()["proposal_dispositions"][expected] == 1
    finally:
        observer.close()


def test_startup_consolidation_failure_is_nonfatal_logged_and_type_only(
    tmp_path, monkeypatch, caplog
):
    """Catches maintenance failure disabling observation or leaking details."""
    database = tmp_path / "categories_v2.db"
    _seed_eligible_proposal(database)

    def fail(*_args, **_kwargs):
        raise sqlite3.DatabaseError("private consolidation details")

    monkeypatch.setattr(category_evolution.EvolutionEngine, "consolidate", fail)
    with caplog.at_level("WARNING", logger="category_evolution"):
        observer = category_evolution.CategoryObserver(database, auto_commit=True)
    try:
        report = observer.report()
        assert report["available"] is True
        assert report["last_error"] == "DatabaseError"
        assert "private consolidation details" not in str(report)
        assert "DatabaseError" in caplog.text
        assert "private consolidation details" not in caplog.text
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


def test_recall_rank_and_outcome_correlation_are_persisted_idempotently(tmp_path):
    """Catches sorted/deduplicated rank loss or outcomes detached from recalls."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    observed_at = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    try:
        observer.observe_recall(
            "ranked recall",
            ["memory-b", "memory-a", "memory-b"],
            source="/workspace",
            observed_at=observed_at,
            recall_id="recall-42",
        )
        observer.observe_outcome("recall-42", True, "used")
        observer.observe_outcome("recall-42", True, "used")

        connection = observer.store.connection
        recall_row = connection.execute(
            "SELECT id, payload_json FROM cat_events WHERE kind='recall_observed'"
        ).fetchone()
        recall_payload = json.loads(recall_row[1])
        assert recall_payload["recall_id"] == "recall-42"
        assert recall_payload["result_ids"] == ["memory-b", "memory-a"]

        proxy_payloads = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM cat_events WHERE kind='proxy_observed' ORDER BY rowid"
            )
        ]
        assert [(item["memory_id"], item["rank"]) for item in proxy_payloads] == [
            ("memory-b", 0),
            ("memory-a", 1),
        ]
        assert all(item["recall_id"] == "recall-42" for item in proxy_payloads)

        outcomes = list(
            connection.execute(
                "SELECT payload_json FROM cat_events WHERE kind='recall_outcome'"
            )
        )
        assert len(outcomes) == 1
        outcome = json.loads(outcomes[0][0])
        assert outcome["correlated"] is True
        assert outcome["recall_event_id"] == recall_row[0]
        assert observer.report()["outcomes"] == {"correlated": 1, "orphaned": 0}
    finally:
        observer.close()


def test_recall_id_makes_observation_retry_idempotent_across_timestamps(tmp_path):
    """The server correlation ID, rather than wall-clock time, identifies a retry."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    started = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    try:
        observer.observe_recall(
            "same recall",
            ["memory"],
            source="/workspace",
            observed_at=started,
            recall_id="retry-id",
        )
        observer.observe_recall(
            "same recall",
            ["memory"],
            source="/workspace",
            observed_at=started + timedelta(seconds=1),
            recall_id="retry-id",
        )

        counts = dict(
            observer.store.connection.execute(
                "SELECT kind, COUNT(*) FROM cat_events GROUP BY kind"
            )
        )
        assert counts == {
            "context_boundary": 1,
            "proxy_observed": 1,
            "recall_observed": 1,
        }
    finally:
        observer.close()


def test_orphan_outcome_is_explicit_in_event_and_report(tmp_path):
    """Catches missing recall IDs being represented as valid correlations."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    try:
        observer.observe_outcome("missing-recall", False, None)
        row = observer.store.connection.execute(
            "SELECT payload_json FROM cat_events WHERE kind='recall_outcome'"
        ).fetchone()
        payload = json.loads(row[0])
        assert payload["correlated"] is False
        assert payload["orphaned"] is True
        assert payload["recall_event_id"] is None
        assert observer.report()["outcomes"] == {"correlated": 0, "orphaned": 1}
    finally:
        observer.close()


def test_orphan_outcome_retry_remains_idempotent_after_recall_arrives(tmp_path):
    """Correlation discovered later must not duplicate an immutable outcome."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    try:
        observer.observe_outcome("late-recall", True, "used")
        observer.observe_recall(
            "late",
            ["memory"],
            source="/workspace",
            observed_at=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
            recall_id="late-recall",
        )
        observer.observe_outcome("late-recall", True, "used")

        outcomes = list(
            observer.store.connection.execute(
                "SELECT payload_json FROM cat_events WHERE kind='recall_outcome'"
            )
        )
        assert len(outcomes) == 1
        assert json.loads(outcomes[0][0])["orphaned"] is True
    finally:
        observer.close()


def test_failed_observation_does_not_advance_boundary_confirmations(
    tmp_path, monkeypatch
):
    """Catches rolled-back SQLite work leaving the in-memory tracker advanced."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    started = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    original_append_event = observer.store.append_event
    try:
        observer.observe_recall(
            "anchor",
            ["memory"],
            source="/workspace",
            observed_at=started,
            recall_id="anchor",
        )

        def fail_boundary(kind, *args, **kwargs):
            if kind == "context_boundary":
                raise sqlite3.DatabaseError("rollback after tracker observation")
            return original_append_event(kind, *args, **kwargs)

        monkeypatch.setattr(observer.store, "append_event", fail_boundary)
        with pytest.raises(sqlite3.DatabaseError):
            observer.observe_recall(
                "candidate",
                ["memory"],
                source="/workspace",
                observed_at=started,
                recall_id="candidate",
            )

        monkeypatch.setattr(observer.store, "append_event", original_append_event)
        observer.observe_recall(
            "candidate",
            ["memory"],
            source="/workspace",
            observed_at=started,
            recall_id="candidate",
        )
        row = observer.store.connection.execute(
            "SELECT payload_json FROM cat_events WHERE kind='context_boundary' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        boundary = json.loads(row[0])
        assert (boundary["kind"], boundary["confirmations"]) == ("soft", 1)
    finally:
        observer.close()


def test_concurrent_observations_are_serialized_into_deterministic_confirmations(tmp_path):
    """Catches shared SQLite/tracker races producing lost or duplicate confirmations."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    observed_at = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    observer.observe_recall(
        "anchor",
        ["memory"],
        source="/workspace",
        observed_at=observed_at,
        recall_id="anchor",
    )
    barrier = threading.Barrier(3)
    errors = []

    def observe(recall_id):
        try:
            barrier.wait()
            observer.observe_recall(
                "candidate",
                ["memory"],
                source="/workspace",
                observed_at=observed_at,
                recall_id=recall_id,
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=observe, args=(f"candidate-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        payloads = [
            json.loads(row[0])
            for row in observer.store.connection.execute(
                "SELECT payload_json FROM cat_events WHERE kind='context_boundary' "
                "ORDER BY rowid"
            )
        ][1:]
        assert [(item["kind"], item["confirmations"]) for item in payloads] == [
            ("soft", 1),
            ("hard", 2),
        ]
    finally:
        observer.close()


def test_observer_can_be_closed_from_another_thread_without_leaking_compiler_pool(tmp_path):
    """Catches thread-bound SQLite handles or compiler connections surviving close."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    compiler = observer.compiler
    errors = []

    def close():
        try:
            observer.close()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=close)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert compiler._closed is True
    assert compiler._available_connections == []
    observer.close()


def test_close_can_retry_after_partial_compiler_failure(tmp_path, monkeypatch):
    """Catches a failed first close poisoning the store or marking closure complete."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    compiler = observer.compiler
    original_close = compiler.close
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("partial close")
        return original_close()

    monkeypatch.setattr(compiler, "close", fail_once)
    with pytest.raises(RuntimeError):
        observer.close()
    assert observer._closed is False
    assert observer.store.connection.execute("SELECT 1").fetchone()[0] == 1

    observer.close()
    assert observer._closed is True
    assert compiler._closed is True


def test_pid_change_reopens_resources_and_reports_process_local_tracker_reset(
    tmp_path, monkeypatch
):
    """Catches child processes using inherited SQLite/compiler/tracker state."""
    pid = {"value": 100}
    monkeypatch.setattr(category_evolution.os, "getpid", lambda: pid["value"])
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    old_compiler = observer.compiler
    observed_at = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    observer.observe_recall(
        "anchor",
        ["memory"],
        source="/workspace",
        observed_at=observed_at,
        recall_id="before-fork",
    )

    pid["value"] = 101
    report = observer.report()

    try:
        assert observer.compiler is not old_compiler
        assert old_compiler._closed is True
        assert report["counts_by_dimension"] == {"0": 1}
        assert report["tracker_state"] == {
            "scope": "process_local",
            "resets": 1,
        }
    finally:
        observer.close()


def test_pid_change_does_not_wait_on_inherited_compiler_condition(
    tmp_path, monkeypatch
):
    """A condition owned by a vanished pre-fork thread cannot block recovery."""
    pid = {"value": 100}
    monkeypatch.setattr(category_evolution.os, "getpid", lambda: pid["value"])
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    inherited_condition = observer.compiler._pool_condition
    held = threading.Event()
    release = threading.Event()

    def hold_condition():
        with inherited_condition:
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_condition)
    holder.start()
    assert held.wait(timeout=5)
    pid["value"] = 101
    finished = threading.Event()

    def recover():
        observer.report()
        finished.set()

    worker = threading.Thread(target=recover)
    worker.start()
    recovered_without_release = finished.wait(timeout=0.25)
    release.set()
    holder.join(timeout=5)
    worker.join(timeout=5)
    try:
        assert recovered_without_release is True
    finally:
        observer.close()


def test_prefork_barrier_waits_for_observer_sqlite_work_to_finish(
    tmp_path, monkeypatch
):
    """A process split cannot capture observer SQLite while it is in use."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    original = observer._observe_recall
    operation_entered = threading.Event()
    allow_operation = threading.Event()
    fork_quiesced = threading.Event()
    allow_parent_release = threading.Event()

    def blocking_observe(*args, **kwargs):
        operation_entered.set()
        allow_operation.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(observer, "_observe_recall", blocking_observe)
    operation = threading.Thread(
        target=observer.observe_recall,
        args=("query", ["memory"]),
        kwargs={
            "source": "/workspace",
            "observed_at": datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
            "recall_id": "recall",
        },
    )

    def fork_hooks():
        category_evolution._before_category_fork()
        fork_quiesced.set()
        allow_parent_release.wait(timeout=5)
        category_evolution._after_category_fork_parent()

    operation.start()
    assert operation_entered.wait(timeout=5)
    fork_thread = threading.Thread(target=fork_hooks)
    fork_thread.start()
    assert fork_quiesced.wait(timeout=0.1) is False
    allow_operation.set()
    operation.join(timeout=5)
    assert fork_quiesced.wait(timeout=5)
    allow_parent_release.set()
    fork_thread.join(timeout=5)
    try:
        assert not operation.is_alive()
        assert not fork_thread.is_alive()
    finally:
        observer.close()


def test_category_module_reload_preserves_fork_registry_without_reregistering(
    tmp_path, monkeypatch
):
    """Hot reload cannot lose live observers or stack duplicate fork hooks."""
    observer = category_evolution.CategoryObserver(tmp_path / "categories_v2.db")
    registry = category_evolution._FORK_OBSERVERS
    registrations = []
    monkeypatch.setattr(
        category_evolution.os,
        "register_at_fork",
        lambda **callbacks: registrations.append(callbacks),
    )
    reloaded = importlib.reload(category_evolution)
    try:
        assert reloaded._FORK_OBSERVERS is registry
        assert observer in reloaded._FORK_OBSERVERS
        assert reloaded._CATEGORY_AT_FORK_REGISTERED is True
        assert registrations == []
    finally:
        observer.close()


def test_real_init_disabled_does_not_create_or_report_category_observer(category_init_env):
    """Catches disabled defaults opening v2 resources or changing absent reflection."""
    server, config, db_path = category_init_env
    config.category_evolution.enabled = False

    server._init()

    assert server._category_observer is None
    assert not (db_path.parent / "categories_v2.db").exists()
    assert server._reflector.reflect("category_evolution") == {
        "category_evolution": {"available": False}
    }


def test_real_init_enabled_uses_graph_sibling_path_thresholds_and_exact_cleanup(
    category_init_env, monkeypatch
):
    """Catches default-path drift, inert thresholds, or mutable-global atexit cleanup."""
    import atexit

    server, config, db_path = category_init_env
    config.category_evolution.enabled = True
    config.category_evolution.db_path = ""
    config.category_evolution.soft_boundary_threshold = 0.22
    config.category_evolution.hard_boundary_threshold = 0.58
    registered = []
    monkeypatch.setattr(atexit, "register", lambda callback: registered.append(callback))

    server._init()

    observer = server._category_observer
    assert observer is not None
    assert observer._database_path == db_path.parent / "categories_v2.db"
    assert observer._tracker._soft_threshold == 0.22
    assert observer._tracker._hard_threshold == 0.58
    cleanup = next(
        callback
        for callback in registered
        if getattr(callback, "_category_observer", None) is observer
    )
    assert cleanup is server._category_atexit_callback

    server.remember("seeded live category report")
    recalled = server.recall("seeded live category", uninvited=0)
    server.log_outcome(recalled["recall_id"], False, "not used")
    report = server._reflector.reflect("category_evolution")["category_evolution"]
    assert report["available"] is True
    assert report["counts_by_dimension"] == {"0": 1}
    assert report["outcomes"] == {"correlated": 1, "orphaned": 0}


def test_real_init_category_constructor_failure_is_reflected_type_only(
    category_init_env, monkeypatch
):
    """Catches enabled init failure becoming indistinguishable from disabled state."""
    server, config, _db_path = category_init_env
    config.category_evolution.enabled = True
    config.category_evolution.shadow = False
    config.category_evolution.influence_recall = True
    config.category_evolution.auto_commit = True

    def fail(*_args, **_kwargs):
        raise sqlite3.DatabaseError("private category path")

    monkeypatch.setattr(category_evolution, "CategoryObserver", fail)
    server._init()

    assert server._category_observer is None
    report = server._reflector.reflect("category_evolution")["category_evolution"]
    assert report == {
        "available": False,
        "flags": {
            "enabled": True,
            "shadow": False,
            "influence_recall": True,
            "auto_commit": True,
        },
        "error": "DatabaseError",
        "last_error": "DatabaseError",
    }
    assert "private category path" not in str(report)
    server.remember("recall remains available after observer init failure")
    assert server.recall("observer init failure", uninvited=0)["results"]


def test_real_reinit_closes_replaced_observer(category_init_env, monkeypatch):
    """Catches reload replacing an observer without closing its compiler/store."""
    server, config, _db_path = category_init_env
    config.category_evolution.enabled = False

    class OldObserver:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    old = OldObserver()
    server._category_observer = old
    server._category_atexit_callback = old.close
    unregistered = []
    monkeypatch.setattr("atexit.unregister", lambda callback: unregistered.append(callback))
    server._init()

    assert old.closed == 1
    assert unregistered == [old.close]


def test_real_reinit_retains_cleanup_callback_when_replaced_observer_close_fails(
    category_init_env, monkeypatch
):
    """A partial close remains retryable through the original exit callback."""
    server, config, _db_path = category_init_env
    config.category_evolution.enabled = False

    class OldObserver:
        def close(self):
            raise RuntimeError("private close detail")

    old = OldObserver()
    server._category_observer = old
    server._category_atexit_callback = old.close
    unregistered = []
    monkeypatch.setattr("atexit.unregister", lambda callback: unregistered.append(callback))

    server._init()

    assert unregistered == []


def test_category_atexit_cleanup_logs_only_failure_type(category_init_env, monkeypatch, caplog):
    """Shutdown cleanup must not let a private close exception reach atexit."""
    import atexit

    server, config, _db_path = category_init_env
    config.category_evolution.enabled = True
    registered = []
    monkeypatch.setattr(atexit, "register", lambda callback: registered.append(callback))
    server._init()
    observer = server._category_observer
    original_close = observer.compiler.close

    def fail_close():
        raise RuntimeError("private shutdown detail")

    monkeypatch.setattr(observer.compiler, "close", fail_close)
    try:
        cleanup = server._category_atexit_callback
        with caplog.at_level("WARNING", logger="server"):
            assert cleanup() is None
        assert "RuntimeError" in caplog.text
        assert "private shutdown detail" not in caplog.text
    finally:
        monkeypatch.setattr(observer.compiler, "close", original_close)


def test_module_reload_retains_observer_until_next_init_can_close_it(monkeypatch):
    """Actual module reload must not discard the only live observer reference."""
    import server

    class OldObserver:
        def close(self):
            pass

    old = OldObserver()
    callback = old.close
    server._category_observer = old
    server._category_atexit_callback = callback
    reloaded = importlib.reload(server)
    try:
        assert reloaded._category_observer is old
        assert reloaded._category_atexit_callback == callback
    finally:
        reloaded._category_observer = None
        reloaded._category_atexit_callback = None


def test_concurrent_server_recalls_timestamp_inside_serialized_observation(
    category_server_env, monkeypatch
):
    """A waiting earlier recall cannot be dropped after a later recall publishes."""
    server, config = category_server_env
    config.category_evolution.enabled = True
    observer = category_evolution.CategoryObserver(
        server.PROJECT_ROOT / "categories_v2.db"
    )
    server._category_observer = observer
    original_observe = observer.observe_recall
    early_entered = threading.Event()
    allow_early = threading.Event()
    late_started = threading.Event()
    late_reached_observer = threading.Event()
    errors = []

    def delayed_observe(*args, **kwargs):
        if kwargs.get("recall_id") == "early":
            early_entered.set()
            allow_early.wait(timeout=5)
        else:
            late_reached_observer.set()
        return original_observe(*args, **kwargs)

    monkeypatch.setattr(observer, "observe_recall", delayed_observe)

    def run(recall_id):
        if recall_id == "late":
            late_started.set()
        try:
            server._observe_category_recall("query", [{"id": recall_id}], recall_id)
        except Exception as exc:
            errors.append(exc)

    early = threading.Thread(target=run, args=("early",))
    late = threading.Thread(target=run, args=("late",))
    early.start()
    assert early_entered.wait(timeout=5)
    late.start()
    assert late_started.wait(timeout=5)
    late_reached_observer.wait(timeout=0.25)
    allow_early.set()
    early.join(timeout=5)
    late.join(timeout=5)
    try:
        assert errors == []
        count = observer.store.connection.execute(
            "SELECT COUNT(*) FROM cat_events WHERE kind='recall_observed'"
        ).fetchone()[0]
        assert count == 2
    finally:
        observer.close()
        server._category_observer = None


def test_init_guard_serializes_concurrent_initialization(monkeypatch):
    """Catches two startup calls entering resource initialization concurrently."""
    import server

    entered = threading.Event()
    release = threading.Event()
    order = []
    order_lock = threading.Lock()

    def guarded_body():
        with order_lock:
            index = sum(item.startswith("enter") for item in order) + 1
            order.append(f"enter-{index}")
        if index == 1:
            entered.set()
            assert release.wait(timeout=5)
        with order_lock:
            order.append(f"exit-{index}")

    monkeypatch.setattr(server, "_init_unlocked", guarded_body)
    first = threading.Thread(target=server._init)
    second = threading.Thread(target=server._init)
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert order == ["enter-1", "exit-1", "enter-2", "exit-2"]


def test_init_guard_is_replaced_after_pid_change(monkeypatch):
    """A child must not wait on an initializer lock owned by a vanished thread."""
    import server

    pid = {"value": 100}
    monkeypatch.setattr(server.os, "getpid", lambda: pid["value"])
    server._init_lock_pid = 100
    inherited_lock = threading.RLock()
    server._init_lock = inherited_lock
    held = threading.Event()
    release = threading.Event()

    def hold_lock():
        with inherited_lock:
            held.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert held.wait(timeout=5)
    pid["value"] = 101
    monkeypatch.setattr(server, "_init_unlocked", lambda: None)
    worker = threading.Thread(target=server._init)
    worker.start()
    worker.join(timeout=0.25)
    completed_before_release = not worker.is_alive()
    release.set()
    holder.join(timeout=5)
    worker.join(timeout=5)

    assert completed_before_release is True


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
