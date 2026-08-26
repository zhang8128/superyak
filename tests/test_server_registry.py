"""Tests for server.py's own silent session_registry stamp (Task 5).

Unlike tests/test_server.py's `server_env` fixture — which stubs module
globals directly and sets `_initialized = True` so `_init()` is a no-op —
this drives the real `server._init()` body against a temp ENGRAM_HOME, the
way tests/test_wake.py exercises the hook-side stamp. Heavy dependencies
(embeddings) are faked; everything else (Storage, Compressor, Reflector,
maintenance passes) runs for real against an empty temp DB.
"""

from __future__ import annotations

import atexit
import json
import math
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import server

from storage import Storage
from watcher import FileWatcher


class _ObservedRLock:
    """RLock that exposes cross-thread contention without timing guesses."""

    def __init__(self):
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._owner = None
        self._depth = 0
        self.contended = threading.Event()

    def acquire(self, *args, **kwargs):
        ident = threading.get_ident()
        with self._state_lock:
            if self._owner is not None and self._owner != ident:
                self.contended.set()
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired:
            with self._state_lock:
                self._owner = ident
                self._depth += 1
        return acquired

    def release(self):
        with self._state_lock:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args):
        self.release()


def _wait_for_child(pid: int, read_fd: int) -> tuple[bytes, int]:
    """Bound a real-fork assertion even if the child deadlocks in C."""
    readable, _, _ = select.select([read_fd], [], [], 5)
    if not readable:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        pytest.fail("fork child did not report within 5 seconds")
    payload = os.read(read_fd, 4096)
    _, status = os.waitpid(pid, 0)
    return payload, status


class FakeEmbeddingProvider:
    """Deterministic, no model download — mirrors tests/test_server.py."""

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


_PROCESS_RESTART_PROBE = textwrap.dedent(
    """
    import json
    import math
    import os
    from pathlib import Path
    import sqlite3
    import sys

    project = Path(sys.argv[1])
    phase = sys.argv[2]
    previous = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None

    import embeddings
    import server
    from config import load_config

    class FakeEmbeddingProvider:
        def dimension(self):
            return 768

        def embed(self, texts, **_kwargs):
            vectors = []
            for text in texts:
                seed = sum(text.encode("utf-8")) or 1
                vector = [float((seed + index) % 17) for index in range(768)]
                norm = math.sqrt(sum(value * value for value in vector))
                vectors.append([value / norm for value in vector])
            return vectors

    embeddings.NomicEmbedProvider = FakeEmbeddingProvider
    config = load_config(project)
    config.graph.enabled = False
    config.watcher.enabled = False
    config.category_evolution.enabled = True
    config.category_evolution.shadow = True
    config.category_evolution.influence_recall = False
    config.category_evolution.auto_commit = False
    server.ENGRAM_HOME = project
    server.DB_PATH = project / ".engram" / "graph.db"
    server.PROJECT_ROOT = project
    server.load_config = lambda _root: config
    server._init()

    observer = server._category_observer
    storage = server._storage
    cleanup = server._server_generation_cleanup
    assert observer is not None
    assert storage is not None
    assert cleanup is not None
    observer_connection = observer.store.connection
    storage_connection = storage.conn

    baseline = [
        {"id": "memory-a", "score": 0.8, "content": "alpha"},
        {"id": "memory-b", "score": 0.4, "content": "beta"},
    ]

    if phase == "a":
        observer_connection.execute(
            "CREATE TEMP TABLE process_a_observer_handle (marker TEXT)"
        )
        storage_connection.execute(
            "CREATE TEMP TABLE process_a_storage_handle (marker TEXT)"
        )
        cleanup.process_marker = "process-a-only"
        delivered = server._observe_category_recall(
            "durable restart event", baseline, "restart-recall-a"
        )
        report = server._reflector.reflect("category_evolution")[
            "category_evolution"
        ]
        assert delivered == baseline
        assert observer._tracker._anchor is not None
        assert report["available"] is True
        payload = {
            "pid": os.getpid(),
            "session_id": server._session_id,
            "event_count": observer_connection.execute(
                "SELECT COUNT(*) FROM cat_events WHERE kind='recall_observed' "
                "AND json_extract(payload_json, '$.recall_id')='restart-recall-a'"
            ).fetchone()[0],
            "shadow_unchanged": delivered == baseline,
        }
    else:
        assert previous is not None
        assert os.getpid() != previous["pid"]
        assert server._session_id != previous["session_id"]
        assert observer._tracker._anchor is None
        assert observer._tracker._pending_candidate is None
        assert observer._tracker._pending_confirmations == 0
        assert not hasattr(cleanup, "process_marker")
        assert observer in cleanup._server_resources
        assert storage in cleanup._server_resources
        assert observer_connection.execute(
            "SELECT COUNT(*) FROM sqlite_temp_master "
            "WHERE name='process_a_observer_handle'"
        ).fetchone()[0] == 0
        assert storage_connection.execute(
            "SELECT COUNT(*) FROM sqlite_temp_master "
            "WHERE name='process_a_storage_handle'"
        ).fetchone()[0] == 0
        durable_event_count = observer_connection.execute(
            "SELECT COUNT(*) FROM cat_events WHERE kind='recall_observed' "
            "AND json_extract(payload_json, '$.recall_id')='restart-recall-a'"
        ).fetchone()[0]
        report = server._reflector.reflect("category_evolution")[
            "category_evolution"
        ]
        assert durable_event_count == 1
        assert report["available"] is True
        assert report["counts_by_dimension"] == {"0": 2}
        delivered = server._observe_category_recall(
            "fresh process shadow event", baseline, "restart-recall-b"
        )
        assert delivered == baseline
        payload = {
            "pid": os.getpid(),
            "durable_event_count": durable_event_count,
            "report_available": report["available"],
            "tracker_fresh": True,
            "callbacks_fresh": True,
            "native_handles_fresh": True,
            "shadow_unchanged": delivered == baseline,
        }

    cleanup()
    for connection in (observer_connection, storage_connection):
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("exact process cleanup left a SQLite handle open")
    print(json.dumps(payload, sort_keys=True))
    """
)


_INITIALIZATION_FAILURE_RACE_PROBE = textwrap.dedent(
    """
    import json
    import os
    import sys
    import threading

    import server

    mode = sys.argv[1]

    class ObservedRLock:
        def __init__(self):
            self._lock = threading.RLock()
            self._state_lock = threading.Lock()
            self._owner = None
            self._depth = 0
            self.contended = threading.Event()

        def acquire(self, *args, **kwargs):
            ident = threading.get_ident()
            with self._state_lock:
                if self._owner is not None and self._owner != ident:
                    self.contended.set()
            acquired = self._lock.acquire(*args, **kwargs)
            if acquired:
                with self._state_lock:
                    self._owner = ident
                    self._depth += 1
            return acquired

        def release(self):
            with self._state_lock:
                self._depth -= 1
                if self._depth == 0:
                    self._owner = None
            self._lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_args):
            self.release()

    class InitFailure(RuntimeError):
        pass

    lifecycle = ObservedRLock()
    published = threading.Event()
    allow_failure = threading.Event()
    cleanup_entered = threading.Event()
    allow_cleanup = threading.Event()
    second_retry_entered = threading.Event()
    first_done = threading.Event()
    second_done = threading.Event()
    calls_lock = threading.Lock()
    observations_lock = threading.Lock()
    calls = 0
    cleanup_calls = 0
    results = {}
    errors = {}

    server._server_lifecycle_lock = lifecycle
    server._init_lock = threading.RLock()
    server._server_pid_guard = threading.RLock()
    server._server_lock_pid = os.getpid()
    server._server_atexit_callbacks = []
    server._server_generation_cleanup = None
    server._initialization_cleanup_required = False
    server._initialized = False

    resource = object()

    def cleanup():
        global cleanup_calls
        if mode == "cleanup-order":
            cleanup_entered.set()
            assert allow_cleanup.wait(timeout=5)
        with calls_lock:
            cleanup_calls += 1

    def controlled_init(**_kwargs):
        global calls
        with calls_lock:
            calls += 1
            call = calls
        if call == 1:
            label = "watcher" if mode == "cleanup-order" else "dependency"
            server._register_server_cleanup(resource, cleanup, label)
            published.set()
            assert allow_failure.wait(timeout=5)
            raise InitFailure("first initializer failed")
        server._initialized = True
        return "ready"

    server._init_unlocked = controlled_init
    real_retry_cleanup = server._retry_failed_initialization_cleanup

    def observed_retry_cleanup():
        if threading.current_thread().name == "second-initializer":
            second_retry_entered.set()
        return real_retry_cleanup()

    server._retry_failed_initialization_cleanup = observed_retry_cleanup

    operation = server._server_operation(server._init)

    def run(name, done, function=server._init):
        try:
            value = function()
        except Exception as exc:
            with observations_lock:
                errors[name] = type(exc).__name__
        else:
            with observations_lock:
                results[name] = value
        finally:
            done.set()

    first = threading.Thread(
        target=run,
        args=(
            "first",
            first_done,
            operation if mode == "wrapped-operation" else server._init,
        ),
        name="first-initializer",
        daemon=True,
    )
    first.start()
    assert published.wait(timeout=5)
    second = threading.Thread(
        target=run,
        args=(
            "second",
            second_done,
            (
                operation
                if mode in {"operation", "wrapped-operation"}
                else server._init
            ),
        ),
        name="second-initializer",
        daemon=True,
    )
    if mode in {"admission", "operation", "wrapped-operation"}:
        second.start()
        assert lifecycle.contended.wait(timeout=5)
        allow_failure.set()
    else:
        allow_failure.set()
        assert cleanup_entered.wait(timeout=5)
        second.start()
        assert second_retry_entered.wait(timeout=5)
        allow_cleanup.set()
    first_finished = first_done.wait(timeout=2)
    second_finished = second_done.wait(timeout=2)
    if mode in {"operation", "wrapped-operation"} and first_finished and second_finished:
        results["retry"] = operation()
    with calls_lock:
        final_calls = calls
        final_cleanup_calls = cleanup_calls
    payload = {
        "calls": final_calls,
        "cleanup_calls": final_cleanup_calls,
        "errors": errors,
        "first_finished": first_finished,
        "results": results,
        "second_finished": second_finished,
    }
    os.write(sys.stdout.fileno(), (json.dumps(payload, sort_keys=True) + "\\n").encode())
    os._exit(0)
    """
)


def _run_process_restart_probe(project: Path, phase: str, previous=None) -> dict:
    command = [sys.executable, "-c", _PROCESS_RESTART_PROBE, str(project), phase]
    if previous is not None:
        command.append(json.dumps(previous, sort_keys=True))
    environment = os.environ.copy()
    environment["ENGRAM_HARNESS"] = "codex"
    environment["ENGRAM_RUN_KEY"] = ""
    environment.pop("CLAUDE_SESSION_ID", None)
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parent.parent,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_process_restart_reopens_durable_shadow_state_with_fresh_runtime_owners(
    tmp_path,
):
    """A clean process replacement keeps disk events, never runtime owners."""
    process_a = _run_process_restart_probe(tmp_path, "a")
    process_b = _run_process_restart_probe(tmp_path, "b", process_a)

    assert process_a["event_count"] == 1
    assert process_a["shadow_unchanged"] is True
    assert process_b == {
        "callbacks_fresh": True,
        "durable_event_count": 1,
        "native_handles_fresh": True,
        "pid": process_b["pid"],
        "report_available": True,
        "shadow_unchanged": True,
        "tracker_fresh": True,
    }


def _run_initialization_failure_race_probe(mode: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _INITIALIZATION_FAILURE_RACE_PROBE, mode],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(completed.stdout.strip())


def _assert_successful_initialization_failure_retry(payload: dict) -> None:
    assert payload == {
        "calls": 2,
        "cleanup_calls": 1,
        "errors": {"first": "InitFailure"},
        "first_finished": True,
        "results": {"second": "ready"},
        "second_finished": True,
    }


def test_failed_first_initializer_cannot_deadlock_concurrent_retry():
    """A waiting initializer is not admitted against the failing owner."""
    _assert_successful_initialization_failure_retry(
        _run_initialization_failure_race_probe("admission")
    )


def test_failed_initialization_cleanup_keeps_one_lock_order_for_retry():
    """A retry never holds lifecycle while waiting for exact cleanup."""
    _assert_successful_initialization_failure_retry(
        _run_initialization_failure_race_probe("cleanup-order")
    )


def test_admitted_tool_rechecks_failed_initialization_before_running():
    """A queued tool drains admission without entering failed resources."""
    assert _run_initialization_failure_race_probe("operation") == {
        "calls": 2,
        "cleanup_calls": 1,
        "errors": {
            "first": "InitFailure",
            "second": "RuntimeError",
        },
        "first_finished": True,
        "results": {"retry": "ready"},
        "second_finished": True,
    }


def test_failed_tool_initialization_cleans_up_after_releasing_outer_barrier():
    """Nested init failure cannot clean while its tool owns lifecycle."""
    assert _run_initialization_failure_race_probe("wrapped-operation") == {
        "calls": 2,
        "cleanup_calls": 1,
        "errors": {
            "first": "InitFailure",
            "second": "RuntimeError",
        },
        "first_finished": True,
        "results": {"retry": "ready"},
        "second_finished": True,
    }


@pytest.fixture
def engram_server_env(tmp_path, monkeypatch):
    """Drive the real server._init() against a temp ENGRAM_HOME.

    Points ENGRAM_HOME/DB_PATH/PROJECT_ROOT at tmp_path, fakes the embedding
    provider (no model download), resets all module globals _init() writes
    to so it actually runs its full body (not skipped via `_initialized`),
    and never inherits harness/session env from the outer shell.
    """
    db_path = tmp_path / ".engram" / "graph.db"
    real_atexit_unregister = atexit.unregister

    for callback in tuple(getattr(server, "_server_atexit_callbacks", ())):
        atexit.unregister(callback)
    server._server_atexit_callbacks.clear()

    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.delenv("ENGRAM_RUN_KEY", raising=False)

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
    monkeypatch.setattr(server, "_category_observer", None)
    monkeypatch.setattr(server, "_category_status", None)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    monkeypatch.setattr(server, "_category_last_observed_at", None)
    monkeypatch.setattr(server, "_server_generation_cleanup", None)
    monkeypatch.setattr(server, "_initialization_cleanup_required", False)
    monkeypatch.setattr(server, "_server_lock_pid", server.os.getpid())
    monkeypatch.setattr(server, "_fork_exec_required", False)

    yield server

    for callback in tuple(server._server_atexit_callbacks):
        real_atexit_unregister(callback)
    server._server_atexit_callbacks.clear()

    if server._category_observer is not None:
        server._category_observer.close()
    if server._category_store is not None:
        server._category_store._conn.close()
    if server._storage is not None:
        server._storage.close()


def test_server_uses_default_instance_for_unbound_project(
    engram_server_env, tmp_path, monkeypatch,
):
    project_root = tmp_path / "unbound-project"
    project_root.mkdir()
    instance_db = tmp_path / ".engram" / "instances" / "engram" / "graph.db"
    instance_db.parent.mkdir(parents=True)
    Storage(str(instance_db)).close()
    monkeypatch.setattr(engram_server_env, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", "engram")

    engram_server_env._init()

    opened_db = Path(
        engram_server_env._storage.conn.execute("PRAGMA database_list").fetchone()[2]
    )
    assert opened_db == instance_db
    assert engram_server_env._instance_name == "engram"


def test_init_stamps_server_session(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    server._init()
    row = server._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (server._session_id,),
    ).fetchone()
    assert row is not None
    assert row["harness"] == "codex"
    assert row["model"] is None
    assert row["repo"]  # cwd recorded


def test_partial_initialization_is_cleaned_before_retry(
    engram_server_env, monkeypatch
):
    """A failed initializer cannot publish replacements over exact live owners."""
    import embeddings

    class InitFailure(RuntimeError):
        pass

    class FailOnceProvider:
        calls = 0

        def __new__(cls):
            cls.calls += 1
            if cls.calls == 1:
                raise InitFailure("provider unavailable")
            return FakeEmbeddingProvider()

    monkeypatch.setattr(embeddings, "NomicEmbedProvider", FailOnceProvider)
    old_storage = None
    try:
        with pytest.raises(InitFailure):
            server._init()

        old_storage = server._storage
        assert old_storage is not None
        with pytest.raises(sqlite3.ProgrammingError):
            old_storage.conn.execute("SELECT 1")
        assert server._initialized is False
        assert server._server_atexit_callbacks == []

        server._init()

        assert server._initialized is True
        assert server._storage is not old_storage
        coordinator = server._server_generation_cleanup
        assert coordinator is not None
        assert server._storage in coordinator._server_resources
    finally:
        if old_storage is not None:
            try:
                old_storage.close()
            except Exception:
                pass


def test_init_stamps_server_session_default_harness(engram_server_env):
    """Without ENGRAM_HARNESS set, the stamp defaults to claude-code."""
    server._init()
    row = server._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (server._session_id,),
    ).fetchone()
    assert row is not None
    assert row["harness"] == "claude-code"
    assert row["model"] is None
    assert row["repo"]


def _seed_bound_hook_row(server_module, run_key="codex:42", session_id="hook-session"):
    from storage import Storage

    db_path = server_module.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(db_path))
    store.stamp_session_registry(
        session_id, harness="codex", model="gpt-5.6-sol", repo=str(server_module.PROJECT_ROOT)
    )
    store.bind_session(run_key, session_id)
    store.close()


def test_codex_init_adopts_bound_hook_session(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "hook-session"
    row = engram_server_env._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (engram_server_env._session_id,),
    ).fetchone()
    assert tuple(row) == ("codex", "gpt-5.6-sol", str(engram_server_env.PROJECT_ROOT))

    result = engram_server_env.remember(
        "Bound Codex session provenance probe", work=True
    )
    episode = engram_server_env._storage.get_episode(result["episode_id"])
    assert episode["session_id"] == "hook-session"


def test_codex_init_without_binding_generates_uuid(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:missing")
    engram_server_env._init()
    assert engram_server_env._session_id != ""
    assert engram_server_env._session_id != "hook-session"

def test_codex_ignores_decoy_claude_session_id(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "decoy-claude")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "hook-session"


def test_claude_session_id_wins_over_inherited_run_key(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "claude-code")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "claude-session"


def test_real_watcher_indexes_with_server_storage_from_worker_thread(
    engram_server_env,
):
    """The lifecycle-serialized watcher can use the server's real SQLite store."""
    source = engram_server_env.PROJECT_ROOT / "worker_owned.py"
    source.write_text("def indexed_from_worker():\n    return 1\n")
    engram_server_env._init()
    finished = threading.Event()
    errors = []

    def index_from_worker():
        try:
            engram_server_env._watcher._index_file(source)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=index_from_worker)
    worker.start()
    assert finished.wait(timeout=5)
    worker.join(timeout=5)

    assert errors == []
    assert engram_server_env._storage.get_entity(
        "symbol:worker_owned.py::indexed_from_worker"
    ) is not None


def test_true_lifo_cleanup_joins_real_watcher_before_closing_storage(
    engram_server_env, monkeypatch, caplog
):
    """The one generation callback drains real indexing before Storage.close."""
    from config import load_config
    from storage import Storage
    from watcher import FileWatcher

    config = load_config(engram_server_env.PROJECT_ROOT)
    config.graph.enabled = False
    config.watcher.enabled = True
    monkeypatch.setattr(engram_server_env, "load_config", lambda _root: config)

    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    real_storage_close = Storage.close
    real_watcher_stop = FileWatcher.stop
    shutdown_stage = threading.Event()
    storage_close_started = threading.Event()
    watcher_stop_started = threading.Event()
    storage_close_calls = []

    def observed_storage_close(storage):
        storage_close_calls.append(storage)
        storage_close_started.set()
        shutdown_stage.set()
        return real_storage_close(storage)

    def observed_watcher_stop(watcher, *args, **kwargs):
        watcher_stop_started.set()
        shutdown_stage.set()
        return real_watcher_stop(watcher, *args, **kwargs)

    monkeypatch.setattr(Storage, "close", observed_storage_close)
    monkeypatch.setattr(FileWatcher, "stop", observed_watcher_stop)
    engram_server_env._init()
    storage = engram_server_env._storage
    watcher = engram_server_env._watcher
    source = engram_server_env.PROJECT_ROOT / "cleanup_owned.py"
    source.write_text("def replacement_symbol():\n    return 2\n")
    index_entered = threading.Event()
    allow_index = threading.Event()
    real_embed = engram_server_env._embeddings.embed

    def block_index_embedding(texts, **kwargs):
        if any("cleanup_owned.py" in text for text in texts):
            index_entered.set()
            assert allow_index.wait(timeout=5)
        return real_embed(texts, **kwargs)

    monkeypatch.setattr(engram_server_env._embeddings, "embed", block_index_embedding)
    watcher.start()
    watcher._queue.put(source)
    assert index_entered.wait(timeout=5)

    shutdown_observations = []

    def release_after_shutdown_blocks():
        assert shutdown_stage.wait(timeout=5)
        shutdown_observations.append(
            (watcher_stop_started.is_set(), storage_close_started.is_set())
        )
        allow_index.set()

    releaser = threading.Thread(target=release_after_shutdown_blocks)
    releaser.start()
    for callback in reversed(tuple(registered)):
        callback()
    releaser.join(timeout=5)

    assert shutdown_observations == [(True, False)]
    assert len(engram_server_env._server_atexit_callbacks) == 1
    assert watcher.is_alive() is False
    assert watcher.processed_count() == 1
    assert storage_close_calls == [storage]


def test_partial_worker_death_blocks_storage_close_until_survivor_joins(
    engram_server_env, monkeypatch, caplog
):
    """Full generation shutdown retains and joins a partially dead pair."""
    from config import load_config
    from storage import Storage
    from watcher import FileWatcher

    config = load_config(engram_server_env.PROJECT_ROOT)
    config.graph.enabled = False
    config.watcher.enabled = True
    monkeypatch.setattr(engram_server_env, "load_config", lambda _root: config)
    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    real_storage_close = Storage.close
    real_watcher_stop = FileWatcher.stop
    storage_close_started = threading.Event()
    watcher_stop_started = threading.Event()

    def observe_storage_close(storage):
        storage_close_started.set()
        return real_storage_close(storage)

    def observe_watcher_stop(watcher, *args, **kwargs):
        watcher_stop_started.set()
        return real_watcher_stop(watcher, *args, **kwargs)

    monkeypatch.setattr(Storage, "close", observe_storage_close)
    monkeypatch.setattr(FileWatcher, "stop", observe_watcher_stop)
    engram_server_env._init()
    watcher = engram_server_env._watcher
    source = engram_server_env.PROJECT_ROOT / "partial_death.py"
    source.write_text("def held_by_survivor():\n    return 1\n")
    producer_exit = threading.Event()
    index_entered = threading.Event()
    allow_index = threading.Event()
    real_embed = engram_server_env._embeddings.embed

    monkeypatch.setattr(watcher, "_watch_loop", lambda: producer_exit.wait(5))

    def block_index(texts, **kwargs):
        if any("partial_death.py" in text for text in texts):
            index_entered.set()
            assert allow_index.wait(timeout=5)
        return real_embed(texts, **kwargs)

    monkeypatch.setattr(engram_server_env._embeddings, "embed", block_index)
    watcher._queue.put(source)
    watcher.start()
    original_threads = tuple(watcher._threads)
    assert index_entered.wait(timeout=5)
    producer_exit.set()
    watcher._watcher_thread.join(timeout=5)
    assert not watcher._watcher_thread.is_alive()
    assert watcher._consumer_thread.is_alive()
    watcher.start()
    assert tuple(watcher._threads) == original_threads

    shutdown_observations = []

    def release_survivor():
        assert watcher_stop_started.wait(timeout=5)
        shutdown_observations.append(not storage_close_started.wait(timeout=0.1))
        allow_index.set()

    releaser = threading.Thread(target=release_survivor)
    releaser.start()
    registered[-1]()
    releaser.join(timeout=5)

    assert shutdown_observations == [True]
    assert storage_close_started.is_set()
    assert all(not thread.is_alive() for thread in original_threads)
    assert "ProgrammingError" not in caplog.text


def test_failed_watcher_join_retains_exact_generation_for_cleanup_retry(
    engram_server_env, monkeypatch
):
    """A bounded join failure cannot close storage or target replacements."""
    from config import load_config
    from storage import Storage
    from watcher import FileWatcher

    config = load_config(engram_server_env.PROJECT_ROOT)
    config.graph.enabled = False
    config.watcher.enabled = True
    monkeypatch.setattr(engram_server_env, "load_config", lambda _root: config)
    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    real_storage_close = Storage.close
    real_watcher_stop = FileWatcher.stop
    stop_attempted = threading.Event()
    storage_close_calls = []

    def observed_storage_close(storage):
        storage_close_calls.append(storage)
        return real_storage_close(storage)

    def bounded_watcher_stop(watcher, *_args, **_kwargs):
        stop_attempted.set()
        return real_watcher_stop(watcher, timeout=0)

    monkeypatch.setattr(Storage, "close", observed_storage_close)
    monkeypatch.setattr(FileWatcher, "stop", bounded_watcher_stop)
    engram_server_env._init()
    storage = engram_server_env._storage
    watcher = engram_server_env._watcher
    source = engram_server_env.PROJECT_ROOT / "retry_cleanup.py"
    source.write_text("def blocked_for_retry():\n    return 3\n")
    index_entered = threading.Event()
    allow_index = threading.Event()
    real_embed = engram_server_env._embeddings.embed

    def block_index_embedding(texts, **kwargs):
        if any("retry_cleanup.py" in text for text in texts):
            index_entered.set()
            assert allow_index.wait(timeout=5)
        return real_embed(texts, **kwargs)

    monkeypatch.setattr(engram_server_env._embeddings, "embed", block_index_embedding)
    watcher.start()
    watcher._queue.put(source)
    assert index_entered.wait(timeout=5)
    callback = registered[-1]
    cleanup_finished = threading.Event()
    cleanup = threading.Thread(
        target=lambda: (callback(), cleanup_finished.set())
    )
    cleanup.start()
    try:
        assert stop_attempted.wait(timeout=5)
        assert cleanup_finished.wait(timeout=5)
        assert storage_close_calls == []
    finally:
        allow_index.set()
        cleanup_finished.wait(timeout=5)
        cleanup.join(timeout=5)

    watcher._consumer_thread.join(timeout=5)
    watcher._watcher_thread.join(timeout=5)
    replacement_calls = []

    class Replacement:
        def close(self):
            replacement_calls.append("close")

        def stop(self):
            replacement_calls.append("stop")

    replacement_storage = Replacement()
    replacement_watcher = Replacement()
    engram_server_env._storage = replacement_storage
    engram_server_env._watcher = replacement_watcher
    try:
        callback()
        callback()
        assert storage_close_calls == [storage]
        assert replacement_calls == []
    finally:
        engram_server_env._storage = storage
        engram_server_env._watcher = watcher


def test_failed_storage_close_retries_after_dependencies_without_double_close(
    engram_server_env, monkeypatch
):
    """Storage remains the last exact step and retries without rerunning owners."""
    from config import load_config
    from storage import Storage
    from watcher import FileWatcher

    config = load_config(engram_server_env.PROJECT_ROOT)
    config.graph.enabled = False
    config.watcher.enabled = False
    monkeypatch.setattr(engram_server_env, "load_config", lambda _root: config)
    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    real_storage_close = Storage.close
    real_watcher_stop = FileWatcher.stop
    storage_attempts = []
    watcher_attempts = []

    def fail_storage_once(storage):
        storage_attempts.append(storage)
        if len(storage_attempts) == 1:
            raise sqlite3.OperationalError("private storage close detail")
        return real_storage_close(storage)

    def observe_watcher_stop(watcher, *args, **kwargs):
        watcher_attempts.append(watcher)
        return real_watcher_stop(watcher, *args, **kwargs)

    monkeypatch.setattr(Storage, "close", fail_storage_once)
    monkeypatch.setattr(FileWatcher, "stop", observe_watcher_stop)
    engram_server_env._init()
    storage = engram_server_env._storage
    watcher = engram_server_env._watcher
    callback = registered[-1]

    callback()

    assert storage.conn.execute("SELECT 1").fetchone()[0] == 1
    assert storage_attempts == [storage]
    assert watcher_attempts == [watcher]
    assert storage in callback._server_resources

    callback()
    callback()

    assert storage_attempts == [storage, storage]
    assert watcher_attempts == [watcher]
    with pytest.raises(sqlite3.ProgrammingError):
        storage.conn.execute("SELECT 1")


def test_queued_server_operation_drains_before_generation_storage_closes(
    tmp_path, monkeypatch
):
    """Work admitted before shutdown finishes against still-open Storage."""
    from storage import Storage

    class OrderedRLock:
        def __init__(self):
            self._condition = threading.Condition()
            self._owner = None
            self._depth = 0
            self._queue = []

        def acquire(self):
            ident = threading.get_ident()
            with self._condition:
                if self._owner == ident:
                    self._depth += 1
                    return True
                token = object()
                self._queue.append(token)
                self._condition.notify_all()
                self._condition.wait_for(
                    lambda: self._owner is None and self._queue[0] is token
                )
                self._queue.pop(0)
                self._owner = ident
                self._depth = 1
                return True

        def release(self):
            with self._condition:
                self._depth -= 1
                if self._depth == 0:
                    self._owner = None
                    self._condition.notify_all()

        def wait_for_queue(self, count):
            with self._condition:
                return self._condition.wait_for(
                    lambda: len(self._queue) >= count, timeout=5
                )

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_args):
            self.release()

    lifecycle = OrderedRLock()
    storage = Storage(str(tmp_path / "queued-cleanup.db"), check_same_thread=False)
    coordinator = server._ServerGenerationCleanup(lifecycle)
    cleanup_started = threading.Event()

    class Watcher:
        def stop(self):
            cleanup_started.set()

    watcher = Watcher()
    coordinator.add(watcher, watcher.stop, "watcher")
    coordinator.add(storage, storage.close, "storage")
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [coordinator])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_server_lock_pid", os.getpid())
    monkeypatch.setattr(
        server,
        "_init_unlocked",
        lambda **_kwargs: storage.conn.execute("SELECT 1").fetchone()[0],
    )
    operation = server._server_operation(server._init)
    cleanup_finished = threading.Event()
    operation_finished = threading.Event()
    operation_errors = []
    operation_results = []

    def clean_generation():
        coordinator()
        cleanup_finished.set()

    def run_queued_operation():
        try:
            operation_results.append(operation())
        except Exception as exc:
            operation_errors.append(exc)
        finally:
            operation_finished.set()

    lifecycle.acquire()
    queued = threading.Thread(target=run_queued_operation)
    queued.start()
    assert lifecycle.wait_for_queue(1)
    cleanup = threading.Thread(target=clean_generation)
    cleanup.start()
    assert cleanup_started.wait(timeout=5)
    assert not cleanup_finished.is_set()
    lifecycle.release()
    assert operation_finished.wait(timeout=5)
    assert cleanup_finished.wait(timeout=5)
    cleanup.join(timeout=5)
    queued.join(timeout=5)

    assert operation_errors == []
    assert operation_results == [1]
    with pytest.raises(RuntimeError, match="generation is shutting down"):
        operation()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        storage.conn.execute("SELECT 1")


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_real_fork_waits_for_blocked_core_initialization_and_resets_child_state(
    monkeypatch,
):
    """Fork cannot cross partial init; child starts with empty process-local state."""
    lifecycle = _ObservedRLock()
    init_entered = threading.Event()
    allow_init = threading.Event()
    release_observed = []
    parent_pid = os.getpid()
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle, raising=False)
    monkeypatch.setattr(server, "_init_lock", threading.RLock())
    monkeypatch.setattr(server, "_server_lock_pid", parent_pid)
    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_recall_scores", {"old": {"memory": 1.0}})
    monkeypatch.setattr(server, "_recall_resonances", {"old": [{"memory_id": "m"}]})
    monkeypatch.setattr(server, "_wander_visits", {"memory": 3})
    monkeypatch.setattr(server, "_last_instinct_id", "instinct")
    monkeypatch.setattr(server, "_session_episode_count", 7)

    def blocked_init(**_kwargs):
        init_entered.set()
        assert allow_init.wait(timeout=5)
        server._initialized = True

    monkeypatch.setattr(server, "_init_unlocked", blocked_init)
    initializer = threading.Thread(target=server._init)
    initializer.start()
    assert init_entered.wait(timeout=5)

    def release_when_fork_waits():
        release_observed.append(lifecycle.contended.wait(timeout=2))
        allow_init.set()

    releaser = threading.Thread(target=release_when_fork_waits)
    releaser.start()

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            clean = (
                server._initialized is False
                and server._recall_scores == {}
                and server._recall_resonances == {}
                and server._wander_visits == {}
                and server._last_instinct_id is None
                and server._session_episode_count == 0
            )
            os.write(write_fd, b"clean" if clean else b"dirty")
            os._exit(0 if clean else 2)
        except BaseException:
            os._exit(3)

    os.close(write_fd)
    payload, status = _wait_for_child(pid, read_fd)
    os.close(read_fd)
    releaser.join(timeout=5)
    initializer.join(timeout=5)

    assert release_observed == [True]
    assert payload == b"clean"
    assert os.waitstatus_to_exitcode(status) == 0
    assert not initializer.is_alive()
    assert server._initialized is True


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_real_fork_quiesces_active_core_sqlite_and_serializes_child_reinit(
    tmp_path, monkeypatch
):
    """A child never uses or replaces an inherited active native generation."""
    import sqlite3

    lifecycle = _ObservedRLock()
    sqlite_entered = threading.Event()
    allow_sqlite = threading.Event()
    release_observed = []
    parent_pid = os.getpid()
    connection = sqlite3.connect(
        tmp_path / "active-core.db", check_same_thread=False
    )
    connection.execute("CREATE TABLE probe(value INTEGER)")
    connection.commit()

    class CoreResource:
        def __init__(self, conn):
            self.conn = conn

    old_storage = CoreResource(connection)
    from category_evolution import CategoryObserver
    from notepad import Notepad

    old_observer = CategoryObserver(tmp_path / "fork-categories.db")
    old_project_notepad = Notepad(tmp_path / "project-notepad.db")
    old_global_notepad = Notepad(tmp_path / "global-notepad.db")

    def block_sqlite():
        sqlite_entered.set()
        assert allow_sqlite.wait(timeout=5)
        return 1

    connection.create_function("block_for_fork", 0, block_sqlite)
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle, raising=False)
    monkeypatch.setattr(server, "_init_lock", threading.RLock())
    monkeypatch.setattr(server, "_server_lock_pid", parent_pid)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_storage", old_storage)
    monkeypatch.setattr(server, "_category_observer", old_observer)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    monkeypatch.setattr(server, "_notepad_project", old_project_notepad)
    monkeypatch.setattr(server, "_notepad_global", old_global_notepad)
    monkeypatch.setattr(server, "_recall_scores", {"old": {"memory": 1.0}})
    monkeypatch.setattr(server, "_recall_resonances", {"old": [{"memory_id": "m"}]})
    monkeypatch.setattr(server, "_wander_visits", {"memory": 2})
    child_init_calls = []

    def initialize_child_once(**_kwargs):
        if server._initialized:
            return
        child_init_calls.append(os.getpid())
        server._storage = object()
        server._initialized = True

    monkeypatch.setattr(server, "_init_unlocked", initialize_child_once)

    def active_sqlite_work():
        return old_storage.conn.execute("SELECT block_for_fork()").fetchone()[0]

    operation = getattr(server, "_server_operation", lambda function: function)(
        active_sqlite_work
    )
    operation_results = []
    worker = threading.Thread(target=lambda: operation_results.append(operation()))
    worker.start()
    assert sqlite_entered.wait(timeout=5)

    def release_when_fork_waits():
        release_observed.append(lifecycle.contended.wait(timeout=2))
        allow_sqlite.set()

    releaser = threading.Thread(target=release_when_fork_waits)
    releaser.start()

    def capture_runtime_error(operation, errors):
        try:
            operation()
        except RuntimeError as exc:
            errors.append("exec" if "exec" in str(exc).lower() else "other")

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            quarantined = getattr(server, "_fork_quarantined_resources", ())
            inherited_is_quarantined = (
                server._storage is None and old_storage in quarantined
                and server._category_observer is None
                and old_observer in quarantined
                and server._notepad_project is None
                and server._notepad_global is None
                and old_project_notepad in quarantined
                and old_global_notepad in quarantined
            )
            errors = []
            first = threading.Thread(
                target=lambda: capture_runtime_error(server._init, errors)
            )
            second = threading.Thread(
                target=lambda: capture_runtime_error(server._init, errors)
            )
            first.start()
            second.start()
            first.join(timeout=2)
            second.join(timeout=2)
            clean = (
                inherited_is_quarantined
                and not first.is_alive()
                and not second.is_alive()
                and len(child_init_calls) == 0
                and errors == ["exec", "exec"]
                and server._recall_scores == {}
                and server._recall_resonances == {}
                and server._wander_visits == {}
                and server._server_atexit_callbacks == []
            )
            os.write(write_fd, b"clean" if clean else b"dirty")
            os._exit(0 if clean else 2)
        except BaseException:
            os._exit(3)

    os.close(write_fd)
    payload, status = _wait_for_child(pid, read_fd)
    os.close(read_fd)
    releaser.join(timeout=5)
    worker.join(timeout=5)
    try:
        assert release_observed == [True]
        assert payload == b"clean"
        assert os.waitstatus_to_exitcode(status) == 0
        assert operation_results == [1]
        assert connection.execute("SELECT 1").fetchone()[0] == 1
        assert old_observer.report()["available"] is True
        assert old_project_notepad.conn.execute("SELECT 1").fetchone()[0] == 1
        assert old_global_notepad.conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        old_observer.close()
        old_project_notepad.close()
        old_global_notepad.close()
        connection.close()


def test_core_atexit_callbacks_close_exact_instances_not_replacement_globals(
    engram_server_env, monkeypatch
):
    """Cleanup registered for one core generation cannot target its successor."""
    registered = []
    monkeypatch.setattr(atexit, "register", lambda callback: registered.append(callback))
    server._init()
    old_storage = server._storage
    old_watcher = server._watcher
    old_category_store = server._category_store
    old_clipboard = server._clipboard
    first_generation_callbacks = tuple(server._server_atexit_callbacks)
    server._init()
    assert tuple(server._server_atexit_callbacks) == first_generation_callbacks
    assert tuple(registered) == first_generation_callbacks
    replacement_calls = []

    class Replacement:
        def stop(self):
            replacement_calls.append("watcher")

        def close(self):
            replacement_calls.append("resource")

    class ReplacementCategoryStore:
        _conn = Replacement()

    server._storage = Replacement()
    server._watcher = Replacement()
    server._knowledge_graph = Replacement()
    server._category_store = ReplacementCategoryStore()
    server._clipboard = Replacement()
    try:
        for callback in registered:
            callback()

        assert replacement_calls == []
        with pytest.raises(sqlite3.ProgrammingError):
            old_storage.conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            old_category_store._conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            old_clipboard._conn.execute("SELECT 1")
    finally:
        server._storage = old_storage
        server._watcher = old_watcher
        server._knowledge_graph = None
        server._category_store = old_category_store
        server._clipboard = old_clipboard


def test_fork_snapshot_retains_detached_generation_coordinator(monkeypatch):
    """Child reset cannot destruct native handles hidden by an orphan callback."""
    resource = object()
    coordinator = server._ServerGenerationCleanup(threading.RLock())
    coordinator.add(resource, lambda: None, "native")
    unregistered = []
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_fork_exec_required", False)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    for name in (
        "_storage",
        "_embeddings",
        "_config",
        "_compressor",
        "_reflector",
        "_watcher",
        "_knowledge_graph",
        "_clipboard",
        "_category_store",
        "_category_observer",
        "_instinct_graph",
        "_notepad_project",
        "_notepad_global",
    ):
        monkeypatch.setattr(server, name, None)

    snapshot = server._server_owned_resources()

    assert coordinator in snapshot
    assert resource in snapshot

    server._reset_server_child_state(snapshot, os.getpid())

    assert unregistered == [coordinator]
    assert coordinator in server._fork_quarantined_resources


def test_initialized_fork_child_requires_exec_before_init_or_serving(monkeypatch):
    """An inherited native generation is a process-replacement boundary."""
    resource = object()
    calls = []
    monkeypatch.setattr(server, "_fork_exec_required", False, raising=False)
    monkeypatch.setattr(server, "_fork_quarantined_resources", [])
    monkeypatch.setattr(server, "_init_unlocked", lambda **_kwargs: calls.append("init"))

    server._reset_server_child_state((resource,), os.getpid())

    for operation in (server._init, server._initialize_pre_serving):
        with pytest.raises(RuntimeError, match="exec"):
            operation()
    assert calls == []
    assert server._fork_quarantined_resources == [resource]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_repeated_fork_quarantine_is_bounded_with_ordinary_child_exit(tmp_path):
    """Descendant forks cannot accumulate resource generations before exec."""
    probe = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path
        import sqlite3
        import sys

        import server

        database = Path(sys.argv[1])
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE probe(value INTEGER)")
        connection.commit()
        server._storage = connection
        server._initialized = True
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            first_size = len(server._fork_quarantined_resources)
            nested = os.fork()
            if nested == 0:
                blocked = []
                for operation in (
                    server._init,
                    server._initialize_pre_serving,
                    lambda: server.recall("must exec", max_results=1),
                ):
                    try:
                        operation()
                    except RuntimeError as exc:
                        blocked.append("exec" in str(exc).lower())
                    else:
                        blocked.append(False)
                os.write(
                    write_fd,
                    json.dumps(
                        {
                            "blocked": blocked,
                            "first_size": first_size,
                            "nested_size": len(server._fork_quarantined_resources),
                        },
                        sort_keys=True,
                    ).encode(),
                )
                sys.exit(0)
            _, nested_status = os.waitpid(nested, 0)
            sys.exit(os.waitstatus_to_exitcode(nested_status))
        os.close(write_fd)
        payload = os.read(read_fd, 4096)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        result = json.loads(payload)
        assert result["blocked"] == [True, True, True]
        assert result["first_size"] > 0
        assert result["nested_size"] == result["first_size"]
        assert connection.execute("SELECT 1").fetchone() == (1,)
        connection.close()
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path / "fork-boundary.db")],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_child_quarantine_unregisters_callback_only_category_observer():
    """A quarantined observer cannot remain in later child fork snapshots."""
    import category_evolution

    class Observer:
        pass

    observer = Observer()
    category_evolution._FORK_OBSERVERS.add(observer)
    try:
        discard = getattr(
            server, "_discard_inherited_category_observers", lambda _resources: None
        )
        discard((observer,))
        assert observer not in category_evolution._FORK_OBSERVERS
    finally:
        category_evolution._FORK_OBSERVERS.discard(observer)


def test_lazy_notepads_register_exact_idempotent_cleanup(
    tmp_path, monkeypatch
):
    """Both lazy SQLite owners are bound once to exact cleanup callbacks."""
    from notepad import Notepad

    project = Notepad(tmp_path / "project.db")
    global_pad = Notepad(tmp_path / "global.db")
    registered = []
    monkeypatch.setattr(server, "_notepad_project", project)
    monkeypatch.setattr(server, "_notepad_global", global_pad)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(atexit, "register", lambda callback: registered.append(callback))

    first = server._get_notepads()
    second = server._get_notepads()

    assert first == second == (project, global_pad)
    assert len(registered) == 1
    assert set(registered[0]._server_resources) == {project, global_pad}
    for callback in registered:
        callback()
        callback()
    with pytest.raises(sqlite3.ProgrammingError):
        project.conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        global_pad.conn.execute("SELECT 1")


def test_nested_same_thread_init_defers_cleanup_until_outer_operation_finishes(
    tmp_path, monkeypatch
):
    """Depth-two admission cannot deadlock or close Storage mid-operation."""
    storage = Storage(
        str(tmp_path / "nested-cleanup.db"), check_same_thread=False
    )
    lifecycle = threading.RLock()
    coordinator = server._ServerGenerationCleanup(lifecycle)

    class Watcher:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    watcher = Watcher()
    coordinator.add(watcher, watcher.stop, "watcher")
    coordinator.add(storage, storage.close, "storage")
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [coordinator])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_initialization_cleanup_required", False)
    monkeypatch.setattr(server, "_server_lock_pid", os.getpid())
    monkeypatch.setattr(
        server,
        "_init_unlocked",
        lambda **_kwargs: storage.conn.execute("SELECT 1").fetchone()[0],
    )
    observations = []

    @server._server_operation
    def outer_operation():
        observations.append(server._init())
        coordinator()
        observations.append(storage.conn.execute("SELECT 1").fetchone()[0])

    outer_operation()

    assert observations == [1, 1]
    assert watcher.stop_calls == 1
    assert storage.conn.execute("SELECT 1").fetchone()[0] == 1

    coordinator()

    assert watcher.stop_calls == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        storage.conn.execute("SELECT 1")
