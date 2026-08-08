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
import importlib
import math
import os
import select
import sqlite3
import threading
import time

import pytest

import server

from category_compile import CategoryCompiler, _DeadlineExceeded
from category_evolution import CategoryObserver
from knowledge import KnowledgeGraph
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
    monkeypatch.setattr(server, "_category_pending_close", None)
    monkeypatch.setattr(server, "_category_status", None)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    monkeypatch.setattr(server, "_category_last_observed_at", None)
    monkeypatch.setattr(server, "_server_generation_cleanup", None)
    monkeypatch.setattr(server, "_server_pending_retirement", None, raising=False)
    monkeypatch.setattr(server, "_server_lifecycle_status", None, raising=False)
    monkeypatch.setattr(server, "_server_reload_reinitialize", False, raising=False)
    monkeypatch.setattr(server, "_server_reload_session_id", None, raising=False)
    monkeypatch.setattr(server, "_server_reload_in_progress", False, raising=False)
    monkeypatch.setattr(server, "_server_lock_pid", server.os.getpid())

    yield server

    for callback in tuple(server._server_atexit_callbacks):
        real_atexit_unregister(callback)
    server._server_atexit_callbacks.clear()

    if server._category_observer is not None:
        server._category_observer.close()
    if server._category_pending_close is not None:
        try:
            server._category_pending_close.close()
        except Exception:
            pass
    if server._category_store is not None:
        server._category_store._conn.close()
    if server._storage is not None:
        server._storage.close()


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


def test_partial_initialization_is_retired_before_retry(
    engram_server_env, monkeypatch
):
    """A failed rebuild cannot be overwritten while exact native owners live."""
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
        pending = server._server_pending_retirement
        assert old_storage is not None
        assert old_storage.conn.execute("SELECT 1").fetchone()[0] == 1
        assert pending is not None
        assert old_storage in pending._server_resources
        assert server._server_atexit_callbacks == [pending]
        assert server._server_lifecycle_status == {
            "available": False,
            "error": "InitFailure",
            "last_error": "InitFailure",
        }

        server._init()

        assert server._initialized is True
        assert server._storage is not old_storage
        with pytest.raises(sqlite3.ProgrammingError):
            old_storage.conn.execute("SELECT 1")
        assert server._server_pending_retirement is None
        coordinator = server._server_generation_cleanup
        assert coordinator._resource_lifecycle_abi == (
            server._SERVER_RESOURCE_LIFECYCLE_ABI
        )
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
    assert "ProgrammingError" not in caplog.text

    for callback in reversed(tuple(registered)):
        callback()
    assert storage_close_calls == [storage]


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
        assert cleanup_finished.wait(timeout=0.25)
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
        lambda: storage.conn.execute("SELECT 1").fetchone()[0],
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

    def blocked_init():
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
    """A child never uses an inherited active handle and initializes core once."""
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
    monkeypatch.setattr(server, "_category_pending_close", None)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    monkeypatch.setattr(server, "_notepad_project", old_project_notepad)
    monkeypatch.setattr(server, "_notepad_global", old_global_notepad)
    monkeypatch.setattr(server, "_recall_scores", {"old": {"memory": 1.0}})
    monkeypatch.setattr(server, "_recall_resonances", {"old": [{"memory_id": "m"}]})
    monkeypatch.setattr(server, "_wander_visits", {"memory": 2})
    child_init_calls = []

    def initialize_child_once():
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
            first = threading.Thread(target=server._init)
            second = threading.Thread(target=server._init)
            first.start()
            second.start()
            first.join(timeout=2)
            second.join(timeout=2)
            clean = (
                inherited_is_quarantined
                and not first.is_alive()
                and not second.is_alive()
                and len(child_init_calls) == 1
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


def test_server_reload_preserves_core_generation_lock_and_cleanup_ownership(
    monkeypatch,
):
    """A marked generation retains exact owners and its reload-stable lock."""
    class Resource:
        def close(self):
            pass

    resource = Resource()
    project_notepad = Resource()
    global_notepad = Resource()
    lifecycle = threading.RLock()
    coordinator = server._ServerGenerationCleanup(lifecycle)
    coordinator.add(resource, resource.close, "storage")
    coordinator.add(project_notepad, project_notepad.close, "project notepad")
    coordinator.add(global_notepad, global_notepad.close, "global notepad")
    coordinator.publish_resource_lifecycle_abi()
    registered = [coordinator]

    def unregister(item):
        registered[:] = [callback for callback in registered if callback is not item]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    monkeypatch.setattr(server, "_storage", resource)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle, raising=False)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [coordinator], raising=False)
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_server_pending_retirement", None, raising=False)
    monkeypatch.setattr(server, "_server_lifecycle_status", None, raising=False)
    monkeypatch.setattr(server, "_server_reload_reinitialize", False, raising=False)
    monkeypatch.setattr(server, "_server_reload_session_id", None, raising=False)
    monkeypatch.setattr(server, "_notepad_project", project_notepad)
    monkeypatch.setattr(server, "_notepad_global", global_notepad)

    reloaded = importlib.reload(server)

    assert reloaded._storage is resource
    assert reloaded._initialized is True
    assert reloaded._server_lifecycle_lock is lifecycle
    assert len(reloaded._server_atexit_callbacks) == 1
    assert reloaded._server_atexit_callbacks[0] is coordinator
    assert coordinator is registered[-1]
    assert getattr(coordinator, "_server_cleanup_coordinator", False) is True
    assert set(coordinator._server_resources) >= {
        resource,
        project_notepad,
        global_notepad,
    }
    assert reloaded._notepad_project is project_notepad
    assert reloaded._notepad_global is global_notepad


def test_reload_keeps_existing_generation_coordinator_registered(monkeypatch):
    """A second reload cannot unregister the already-adopted exact callback."""
    class Observer:
        def close(self):
            pass

    observer = Observer()
    lifecycle = threading.RLock()
    coordinator = server._ServerGenerationCleanup(lifecycle)
    coordinator.add(observer, observer.close, "category observer")
    coordinator.publish_resource_lifecycle_abi()
    registered = [coordinator]
    unregistered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [coordinator])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_server_pending_retirement", None, raising=False)
    monkeypatch.setattr(server, "_server_lifecycle_status", None, raising=False)
    monkeypatch.setattr(server, "_server_reload_reinitialize", False, raising=False)
    monkeypatch.setattr(server, "_server_reload_session_id", None, raising=False)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_category_observer", observer)
    monkeypatch.setattr(server, "_category_pending_close", None)
    monkeypatch.setattr(server, "_category_atexit_callback", coordinator)
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_knowledge_graph", None)
    monkeypatch.setattr(server, "_category_store", None)
    monkeypatch.setattr(server, "_clipboard", None)
    monkeypatch.setattr(server, "_instinct_graph", None)
    monkeypatch.setattr(server, "_notepad_project", None)
    monkeypatch.setattr(server, "_notepad_global", None)

    reloaded = importlib.reload(server)

    assert reloaded._server_lifecycle_lock is lifecycle
    assert reloaded._server_atexit_callbacks == [coordinator]
    assert reloaded._category_atexit_callback is coordinator
    assert registered == [coordinator]
    assert unregistered == []


def test_reload_drains_and_retires_lazy_owners_published_after_snapshot(
    monkeypatch,
):
    """An old request cannot publish callback-owned SQLite state past migration."""
    lifecycle = threading.RLock()
    request_holds_lifecycle = threading.Event()
    stop_seen = threading.Event()
    late_done = threading.Event()

    class Watcher:
        _watcher_thread = None
        _consumer_thread = None

        def stop(self):
            stop_seen.set()

        def is_alive(self):
            return False

    class LateOwner:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    watcher = Watcher()
    project = LateOwner()
    global_pad = LateOwner()
    registered = []

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    for name, value in {
        "_initialized": False,
        "_storage": None,
        "_embeddings": None,
        "_config": None,
        "_compressor": None,
        "_reflector": None,
        "_watcher": watcher,
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_instinct_graph": None,
        "_notepad_project": None,
        "_notepad_global": None,
        "_server_lifecycle_lock": lifecycle,
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_reinitialize": False,
        "_server_reload_session_id": None,
        "_server_reload_in_progress": False,
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    def old_request():
        with lifecycle:
            request_holds_lifecycle.set()
            assert stop_seen.wait(timeout=5)
            server._notepad_project = project
            server._notepad_global = global_pad
            server._register_server_cleanup(
                project, project.close, "project notepad"
            )
            server._register_server_cleanup(
                global_pad, global_pad.close, "global notepad"
            )
            late_done.set()

    request = threading.Thread(target=old_request)
    request.start()
    assert request_holds_lifecycle.wait(timeout=5)

    reloaded = importlib.reload(server)
    request.join(timeout=5)

    assert late_done.is_set() is True
    assert request.is_alive() is False
    assert project.close_calls == 1
    assert global_pad.close_calls == 1
    assert reloaded._notepad_project is None
    assert reloaded._notepad_global is None
    assert reloaded._server_generation_cleanup is None
    assert reloaded._server_pending_retirement is None
    assert reloaded._server_atexit_callbacks == []
    assert registered == []


def test_reload_rebuilds_when_old_initializer_publishes_after_capture(
    tmp_path, monkeypatch
):
    """Late `_initialized=True` cannot survive retirement with empty owners."""
    lifecycle = threading.RLock()
    initializer_holds_lifecycle = threading.Event()
    stop_seen = threading.Event()
    published = threading.Event()

    class Watcher:
        _watcher_thread = None
        _consumer_thread = None

        def stop(self):
            stop_seen.set()

        def is_alive(self):
            return False

    class LateStorage:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    watcher = Watcher()
    late_storage = LateStorage()
    config = _reload_config(tmp_path, watcher=False, category=False)
    registered = []

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    monkeypatch.setattr("config.load_config", lambda _root: config)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", FakeEmbeddingProvider)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setenv("ENGRAM_PROJECT_ROOT", str(tmp_path))
    for name, value in {
        "_initialized": False,
        "_storage": None,
        "_embeddings": None,
        "_config": config,
        "_compressor": None,
        "_reflector": None,
        "_watcher": watcher,
        "_session_id": None,
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_status": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_instinct_graph": None,
        "_notepad_project": None,
        "_notepad_global": None,
        "_server_lifecycle_lock": lifecycle,
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_reinitialize": False,
        "_server_reload_session_id": None,
        "_server_reload_in_progress": False,
        "_server_lock_pid": os.getpid(),
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    def old_initializer():
        with lifecycle:
            initializer_holds_lifecycle.set()
            assert stop_seen.wait(timeout=5)
            server._storage = late_storage
            server._session_id = "late-session"
            server._initialized = True
            published.set()

    initializer = threading.Thread(target=old_initializer)
    initializer.start()
    assert initializer_holds_lifecycle.wait(timeout=5)
    replacement_coordinator = None
    try:
        reloaded = importlib.reload(server)
        replacement_coordinator = reloaded._server_generation_cleanup
        initializer.join(timeout=5)

        assert published.is_set() is True
        assert not initializer.is_alive()
        assert late_storage.close_calls == 1
        assert reloaded._initialized is True
        assert reloaded._storage is not None
        assert reloaded._storage is not late_storage
        assert reloaded._session_id == "late-session"
        assert reloaded._server_pending_retirement is None
        assert replacement_coordinator._resource_lifecycle_abi == (
            reloaded._SERVER_RESOURCE_LIFECYCLE_ABI
        )
        assert registered == [replacement_coordinator]
    finally:
        stop_seen.set()
        initializer.join(timeout=5)
        if replacement_coordinator is not None:
            replacement_coordinator()


def test_reload_rebuilds_marked_generation_after_shutdown_has_started(
    tmp_path, monkeypatch
):
    """A closing same-ABI owner is terminal state, not reload-compatible state."""
    config = _reload_config(tmp_path, watcher=False, category=False)
    registered = []

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "DB_PATH", tmp_path / ".engram" / "graph.db")
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(server, "load_config", lambda _root: config)
    monkeypatch.setattr("config.load_config", lambda _root: config)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", FakeEmbeddingProvider)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setenv("ENGRAM_PROJECT_ROOT", str(tmp_path))
    for name, value in {
        "_initialized": False,
        "_storage": None,
        "_embeddings": None,
        "_config": None,
        "_compressor": None,
        "_reflector": None,
        "_watcher": None,
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_status": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_reinitialize": False,
        "_server_reload_session_id": None,
        "_server_reload_in_progress": False,
        "_server_lock_pid": os.getpid(),
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    server._init()
    old_storage = server._storage
    old_coordinator = server._server_generation_cleanup

    class ExtraOwner:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    extra = ExtraOwner()
    old_coordinator.add(extra, extra.close, "extra owner")
    old_coordinator()
    assert old_coordinator.closing is True
    assert extra.close_calls == 1

    reloaded = importlib.reload(server)
    replacement = reloaded._server_generation_cleanup
    try:
        assert reloaded._initialized is True
        assert reloaded._storage is not old_storage
        assert replacement is not old_coordinator
        assert replacement.closing is False
        assert replacement._resource_lifecycle_abi == (
            reloaded._SERVER_RESOURCE_LIFECYCLE_ABI
        )
        assert extra.close_calls == 1
        assert registered == [replacement]
    finally:
        if replacement is not None:
            replacement()


def test_legacy_request_does_not_deadlock_reload_preparation_lock():
    """A pre-reload wrapper holding lifecycle fails the reload gate promptly."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            lifecycle = threading.RLock()
            stop_seen = threading.Event()
            request_holds_lifecycle = threading.Event()
            reload_done = threading.Event()
            request_done = threading.Event()
            request_errors = []

            class Watcher:
                _watcher_thread = None
                _consumer_thread = None

                def stop(self):
                    stop_seen.set()
                    assert request_holds_lifecycle.wait(timeout=3)

                def is_alive(self):
                    return False

            for name, value in {
                "_initialized": False,
                "_storage": None,
                "_embeddings": None,
                "_config": None,
                "_compressor": None,
                "_reflector": None,
                "_watcher": Watcher(),
                "_knowledge_graph": None,
                "_category_store": None,
                "_category_observer": None,
                "_category_pending_close": None,
                "_category_atexit_callback": None,
                "_clipboard": None,
                "_instinct_graph": None,
                "_notepad_project": None,
                "_notepad_global": None,
                "_server_lifecycle_lock": lifecycle,
                "_server_atexit_callbacks": [],
                "_server_generation_cleanup": None,
                "_server_pending_retirement": None,
                "_server_lifecycle_status": None,
                "_server_reload_reinitialize": False,
                "_server_reload_session_id": None,
                "_server_reload_in_progress": False,
            }.items():
                setattr(server, name, value)

            def reload_server():
                try:
                    importlib.reload(server)
                finally:
                    reload_done.set()

            def legacy_request():
                assert stop_seen.wait(timeout=3)
                with lifecycle:
                    request_holds_lifecycle.set()
                    try:
                        server._init()
                    except Exception as exc:
                        request_errors.append(exc)
                request_done.set()

            reload_thread = threading.Thread(target=reload_server, daemon=True)
            request_thread = threading.Thread(target=legacy_request, daemon=True)
            reload_thread.start()
            request_thread.start()
            reload_thread.join(timeout=3)
            request_thread.join(timeout=3)
            clean = (
                reload_done.is_set()
                and request_done.is_set()
                and not reload_thread.is_alive()
                and not request_thread.is_alive()
                and len(request_errors) == 1
                and isinstance(request_errors[0], RuntimeError)
                and "server generation unavailable" in str(request_errors[0])
            )
            os.write(write_fd, b"clean" if clean else b"deadlock")
            os._exit(0 if clean else 2)
        except BaseException:
            os._exit(3)

    os.close(write_fd)
    payload, status = _wait_for_child(pid, read_fd)
    os.close(read_fd)
    assert payload == b"clean"
    assert os.waitstatus_to_exitcode(status) == 0


def test_same_thread_reload_defers_retirement_until_lifecycle_is_released(
    monkeypatch,
):
    """Reload from inside the old RLock cannot close an active generation."""
    lifecycle = threading.RLock()
    registered = []

    class Resource:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    resource = Resource()

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    for name, value in {
        "_initialized": False,
        "_storage": resource,
        "_embeddings": None,
        "_config": None,
        "_compressor": None,
        "_reflector": None,
        "_watcher": None,
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_instinct_graph": None,
        "_notepad_project": None,
        "_notepad_global": None,
        "_server_lifecycle_lock": lifecycle,
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_reinitialize": False,
        "_server_reload_session_id": None,
        "_server_reload_in_progress": False,
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    with lifecycle:
        reloaded = importlib.reload(server)
        assert resource.close_calls == 0
        assert reloaded._storage is resource
        assert reloaded._server_pending_retirement is not None

    reloaded._prepare_server_generation()

    assert resource.close_calls == 1
    assert reloaded._storage is None
    assert reloaded._server_pending_retirement is None
    assert reloaded._server_atexit_callbacks == []
    assert registered == []


def test_reload_gate_rejects_init_before_current_module_publication(monkeypatch):
    """No stale `_init_unlocked` can run while reload publication is closed."""
    called = []
    monkeypatch.setattr(server, "_server_reload_in_progress", True)
    monkeypatch.setattr(server, "_server_pending_retirement", None)
    monkeypatch.setattr(server, "_init_unlocked", lambda: called.append(True))

    with pytest.raises(RuntimeError, match="server generation unavailable"):
        server._init()

    assert called == []


def test_real_fork_waits_for_complete_reload_publication(monkeypatch):
    """A child cannot observe the initializer preserved mid-server reload."""
    class ObservedCondition(threading.Condition):
        def __init__(self):
            super().__init__(threading.RLock())
            self.fork_waiting = threading.Event()

        def wait(self, timeout=None):
            self.fork_waiting.set()
            return super().wait(timeout)

    condition = ObservedCondition()
    stop_seen = threading.Event()
    allow_stop = threading.Event()
    reload_done = threading.Event()
    fork_done = threading.Event()
    fork_results = []

    class Watcher:
        _watcher_thread = None
        _consumer_thread = None

        def stop(self):
            stop_seen.set()
            assert allow_stop.wait(timeout=5)

        def is_alive(self):
            return False

    def stale_init():
        return "stale"

    for name, value in {
        "_initialized": False,
        "_storage": None,
        "_embeddings": None,
        "_config": None,
        "_compressor": None,
        "_reflector": None,
        "_watcher": Watcher(),
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_instinct_graph": None,
        "_notepad_project": None,
        "_notepad_global": None,
        "_server_lifecycle_lock": threading.RLock(),
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_reinitialize": False,
        "_server_reload_session_id": None,
        "_server_reload_in_progress": False,
        "_server_reload_fork_condition": condition,
        "_server_reload_fork_gate_held": False,
        "_server_lifecycle_fork_gate_held": False,
        "_init_unlocked": stale_init,
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    def reload_server():
        try:
            importlib.reload(server)
        finally:
            reload_done.set()

    read_fd, write_fd = os.pipe()

    def fork_while_reloading():
        pid = os.fork()
        if pid == 0:
            try:
                os.close(read_fd)
                current = (
                    server._init_unlocked is not stale_init
                    and server._server_reload_in_progress is False
                )
                os.write(write_fd, b"current" if current else b"stale")
                os._exit(0 if current else 2)
            except BaseException:
                os._exit(3)
        os.close(write_fd)
        payload, status = _wait_for_child(pid, read_fd)
        os.close(read_fd)
        fork_results.append((payload, os.waitstatus_to_exitcode(status)))
        fork_done.set()

    reload_thread = threading.Thread(target=reload_server)
    reload_thread.start()
    assert stop_seen.wait(timeout=5)
    fork_thread = threading.Thread(target=fork_while_reloading)
    fork_thread.start()
    assert condition.fork_waiting.wait(timeout=5)
    assert reload_done.is_set() is False
    assert fork_done.is_set() is False

    allow_stop.set()
    reload_thread.join(timeout=5)
    fork_thread.join(timeout=5)

    assert not reload_thread.is_alive()
    assert not fork_thread.is_alive()
    assert fork_results == [(b"current", 0)]


def test_reload_prerequisite_failure_does_not_poison_fork_gate(monkeypatch):
    """Failure before publication leaves the preserved generation gate open."""
    fastmcp = importlib.import_module("mcp.server.fastmcp")
    original_fastmcp = fastmcp.FastMCP
    preserved_mcp = server.mcp

    class ReloadPrerequisiteFailure(RuntimeError):
        pass

    def fail_fastmcp(*_args, **_kwargs):
        raise ReloadPrerequisiteFailure("constructor unavailable")

    monkeypatch.setattr(fastmcp, "FastMCP", fail_fastmcp)
    try:
        with pytest.raises(ReloadPrerequisiteFailure):
            importlib.reload(server)

        flag_after_failure = server._server_reload_in_progress
        gate_returned = threading.Event()

        def enter_and_release_gate():
            server._before_server_reload_fork_gate()
            gate_returned.set()
            server._after_server_reload_fork_parent_gate()

        gate_thread = threading.Thread(
            target=enter_and_release_gate, daemon=True
        )
        gate_thread.start()
        returned_without_repair = gate_returned.wait(timeout=1)
        if not returned_without_repair:
            with server._server_reload_fork_condition:
                server._server_reload_in_progress = False
                server._server_reload_fork_condition.notify_all()
        gate_thread.join(timeout=1)

        assert flag_after_failure is False
        assert returned_without_repair is True
        assert server.mcp is preserved_mcp
        assert not gate_thread.is_alive()
    finally:
        monkeypatch.setattr(fastmcp, "FastMCP", original_fastmcp)
        if server._server_reload_in_progress:
            with server._server_reload_fork_condition:
                server._server_reload_in_progress = False
                server._server_reload_fork_condition.notify_all()
        importlib.reload(server)


def test_tool_registration_failure_surfaces_after_reload_gate_reopens(
    monkeypatch,
):
    """A staged MCP schema failure cannot poison fork or replace serving MCP."""
    fastmcp = importlib.import_module("mcp.server.fastmcp")
    original_fastmcp = fastmcp.FastMCP
    preserved_mcp = server.mcp

    class BadMCP:
        def tool(self, *_args, **_kwargs):
            raise RuntimeError("private tool-registration detail")

    monkeypatch.setattr(fastmcp, "FastMCP", lambda *_args, **_kwargs: BadMCP())
    gate_thread = None
    try:
        with pytest.raises(RuntimeError) as caught:
            importlib.reload(server)

        flag_after_failure = server._server_reload_in_progress
        gate_returned = threading.Event()

        def enter_and_release_gate():
            server._before_server_reload_fork_gate()
            gate_returned.set()
            server._after_server_reload_fork_parent_gate()

        gate_thread = threading.Thread(
            target=enter_and_release_gate, daemon=True
        )
        gate_thread.start()
        returned_without_repair = gate_returned.wait(timeout=1)
        if not returned_without_repair:
            with server._server_reload_fork_condition:
                server._server_reload_in_progress = False
                server._server_reload_fork_condition.notify_all()
        gate_thread.join(timeout=1)

        assert type(caught.value) is RuntimeError
        assert "private tool-registration detail" not in str(caught.value)
        assert flag_after_failure is False
        assert returned_without_repair is True
        assert server.mcp is preserved_mcp
        assert not gate_thread.is_alive()
    finally:
        monkeypatch.setattr(fastmcp, "FastMCP", original_fastmcp)
        if server._server_reload_in_progress:
            with server._server_reload_fork_condition:
                server._server_reload_in_progress = False
                server._server_reload_fork_condition.notify_all()
        if gate_thread is not None:
            gate_thread.join(timeout=1)
        importlib.reload(server)


def test_init_rechecks_generation_after_preparation_before_entering_lifecycle(
    monkeypatch,
):
    """A pending retirement published after precheck still blocks init."""
    precheck_finished = threading.Event()
    resume_admission = threading.Event()
    original_admit = server._admit_server_operation
    init_calls = []
    results = []
    errors = []

    def paused_admit():
        precheck_finished.set()
        assert resume_admission.wait(timeout=2)
        return original_admit()

    monkeypatch.setattr(server, "_server_reload_in_progress", False)
    monkeypatch.setattr(server, "_server_pending_retirement", None)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(server, "_server_generation_cleanup", None)
    monkeypatch.setattr(server, "_admit_server_operation", paused_admit)
    monkeypatch.setattr(
        server,
        "_init_unlocked",
        lambda: init_calls.append("replacement-built") or "built",
    )

    def initialize():
        try:
            results.append(server._init())
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=initialize)
    worker.start()
    assert precheck_finished.wait(timeout=2)
    pending = object()
    server._server_pending_retirement = pending
    resume_admission.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "server generation unavailable" in str(errors[0])
    assert init_calls == []
    assert server._server_pending_retirement is pending


def test_legacy_compiler_retirement_defers_from_its_lease_owner():
    """Compatibility cleanup cannot wait for a lease owned by its caller."""
    condition = threading.Condition()
    handle = object()
    compiler = type("LegacyCompiler", (), {})()
    compiler._pool_condition = condition
    compiler._available_connections = []
    compiler._leased_connections = {}
    compiler._closing = False
    compiler._closed = False
    compiler._close_in_progress = False
    compiler._shutdown_errors = []
    retirement = server._LegacyServerGenerationRetirement(
        threading.RLock(), None, (), {}
    )
    errors = []
    finished = threading.Event()

    def close_from_lease_owner():
        with condition:
            compiler._leased_connections[handle] = threading.get_ident()
        try:
            retirement._close_legacy_compiler(compiler)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=close_from_lease_owner, daemon=True)
    worker.start()
    completed_without_waiting = finished.wait(timeout=1)
    if not completed_without_waiting:
        # Keep a RED run bounded even though the broken implementation waits
        # forever for the exact lease held by this same worker.
        with condition:
            compiler._leased_connections.clear()
            condition.notify_all()
    worker.join(timeout=1)

    assert completed_without_waiting is True
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "connection lease" in str(errors[0])
    assert compiler._leased_connections == {handle: worker.ident}
    assert compiler._closing is False
    assert compiler._closed is False
    assert compiler._close_in_progress is False


def test_fork_snapshot_retains_resources_owned_only_by_exact_cleanup_callback(
    monkeypatch,
):
    """Child quarantine keeps callback-only native owners from destructing."""
    resource = object()
    category_resource = type("CategoryResource", (), {"close": lambda self: None})()
    callback = server._make_server_cleanup(resource, lambda: None, "native")
    monkeypatch.setattr(server, "_server_atexit_callbacks", [callback])
    monkeypatch.setattr(
        server,
        "_category_atexit_callback",
        server._make_category_cleanup(category_resource),
    )
    monkeypatch.setattr(server, "_category_observer", None)
    monkeypatch.setattr(server, "_category_pending_close", None)
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_knowledge_graph", None)

    snapshot = server._server_owned_resources()

    assert resource in snapshot
    assert category_resource in snapshot


def test_fork_snapshot_retains_detached_generation_coordinator(monkeypatch):
    """Child reset cannot destruct native handles hidden by an orphan callback."""
    resource = object()
    coordinator = server._ServerGenerationCleanup(threading.RLock())
    coordinator.add(resource, lambda: None, "native")
    unregistered = []
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
    monkeypatch.setattr(server, "_server_pending_retirement", None)
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
        "_category_pending_close",
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


def test_exact_core_cleanup_callback_is_idempotent_after_success():
    """Repeated cleanup registration execution cannot close one owner twice."""
    calls = []
    resource = object()
    callback = server._make_server_cleanup(
        resource, lambda: calls.append(resource), "resource"
    )

    callback()
    callback()

    assert calls == [resource]


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


def test_reload_upgrades_legacy_child_only_atfork_registration(monkeypatch):
    """A legacy boolean cannot suppress the new three-phase lifecycle hook."""
    registrations = []
    monkeypatch.setattr(
        server.os,
        "register_at_fork",
        lambda **callbacks: registrations.append(callbacks),
    )
    monkeypatch.setattr(server, "_SERVER_AT_FORK_REGISTERED", True)
    monkeypatch.delattr(
        server, "_SERVER_AT_FORK_LIFECYCLE_VERSION", raising=False
    )

    reloaded = importlib.reload(server)

    assert len(registrations) == 1
    assert set(registrations[0]) == {
        "before",
        "after_in_parent",
        "after_in_child",
    }
    assert reloaded._SERVER_AT_FORK_LIFECYCLE_VERSION == 2


def test_legacy_atfork_upgrade_waits_for_reload_before_lifecycle_lock(
    monkeypatch,
):
    """The newly installed lifecycle hook cannot lock ahead of the gate."""
    class ObservedCondition(threading.Condition):
        def __init__(self):
            super().__init__(threading.RLock())
            self.waiting = threading.Event()

        def wait(self, timeout=None):
            self.waiting.set()
            return super().wait(timeout)

    condition = ObservedCondition()
    registrations = []
    monkeypatch.setattr(
        server.os,
        "register_at_fork",
        lambda **callbacks: registrations.append(callbacks),
    )
    monkeypatch.setattr(server, "_server_reload_fork_condition", condition)
    monkeypatch.setattr(
        server, "_SERVER_RELOAD_GATE_AT_FORK_REGISTERED", False
    )
    monkeypatch.setattr(server, "_SERVER_AT_FORK_REGISTERED", True)
    monkeypatch.setattr(server, "_SERVER_AT_FORK_LIFECYCLE_VERSION", 0)
    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(server, "_server_generation_cleanup", None)
    monkeypatch.setattr(server, "_server_pending_retirement", None)
    for name in (
        "_storage",
        "_watcher",
        "_knowledge_graph",
        "_category_store",
        "_category_observer",
        "_category_pending_close",
        "_clipboard",
        "_instinct_graph",
        "_notepad_project",
        "_notepad_global",
    ):
        monkeypatch.setattr(server, name, None)

    reloaded = importlib.reload(server)
    assert len(registrations) == 2
    with condition:
        reloaded._server_reload_in_progress = True

    before_done = threading.Event()
    run_parent_callbacks = threading.Event()

    def run_fork_callbacks():
        for registration in reversed(registrations):
            registration["before"]()
        before_done.set()
        assert run_parent_callbacks.wait(timeout=2)
        for registration in registrations:
            registration["after_in_parent"]()

    fork_thread = threading.Thread(target=run_fork_callbacks, daemon=True)
    fork_thread.start()
    assert condition.waiting.wait(timeout=2)

    lifecycle_was_free = reloaded._server_lifecycle_lock.acquire(
        blocking=False
    )
    if lifecycle_was_free:
        reloaded._server_lifecycle_lock.release()

    with condition:
        reloaded._server_reload_in_progress = False
        condition.notify_all()
    assert before_done.wait(timeout=2)
    run_parent_callbacks.set()
    fork_thread.join(timeout=2)

    assert lifecycle_was_free is True
    assert not fork_thread.is_alive()


def test_reload_migration_masks_legacy_dynamic_atexit_callbacks_after_fork(
    monkeypatch,
):
    """Legacy dynamic callbacks cannot double-close a child generation."""
    class Resource:
        def __init__(self):
            self.close_count = 0

        def close(self):
            self.close_count += 1

        def stop(self):
            self.close()

    registered = [
        lambda: server._watcher.stop() if server._watcher else None,
        lambda: server._storage.close() if server._storage else None,
        lambda: server._knowledge_graph.close()
        if server._knowledge_graph
        else None,
        lambda: server._category_store._conn.close()
        if server._category_store
        else None,
        lambda: server._clipboard.close() if server._clipboard else None,
    ]

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    monkeypatch.setattr(server.os, "register_at_fork", lambda **_callbacks: None)
    monkeypatch.setattr(server, "_storage", None)
    monkeypatch.setattr(server, "_watcher", None)
    monkeypatch.setattr(server, "_knowledge_graph", None)
    monkeypatch.setattr(server, "_category_store", None)
    monkeypatch.setattr(server, "_clipboard", None)
    monkeypatch.setattr(server, "_instinct_graph", None)
    monkeypatch.setattr(server, "_notepad_project", None)
    monkeypatch.setattr(server, "_notepad_global", None)
    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
    monkeypatch.setattr(server, "_server_generation_cleanup", None)
    monkeypatch.setattr(server, "_server_pending_retirement", None, raising=False)
    monkeypatch.setattr(server, "_server_reload_reinitialize", False, raising=False)
    monkeypatch.setattr(server, "_server_reload_session_id", None, raising=False)
    monkeypatch.setattr(server, "_category_observer", None)
    monkeypatch.setattr(server, "_category_pending_close", None)
    monkeypatch.setattr(server, "_category_atexit_callback", None)
    monkeypatch.setattr(server, "_SERVER_AT_FORK_REGISTERED", True)
    monkeypatch.delattr(
        server, "_SERVER_AT_FORK_LIFECYCLE_VERSION", raising=False
    )
    monkeypatch.delattr(
        server, "_legacy_dynamic_atexit_guard", raising=False
    )
    monkeypatch.delattr(
        server, "_LEGACY_DYNAMIC_ATEXIT_REQUIRED", raising=False
    )

    reloaded = importlib.reload(server)

    resources = reloaded._server_owned_resources()
    reloaded._reset_server_child_state(resources, os.getpid())
    child_storage = Resource()
    reloaded._storage = child_storage
    reloaded._register_server_cleanup(
        child_storage, child_storage.close, "storage"
    )

    for callback in reversed(tuple(registered)):
        callback()

    assert child_storage.close_count == 1


class _PriorRevisionStorage(Storage):
    """Real Storage with the pre-b7a31f5 close contract."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.legacy_close_calls = 0

    def close(self) -> None:
        self.legacy_close_calls += 1
        if hasattr(self, "_cold_conn") and self._cold_conn is not None:
            try:
                self._cold_conn.close()
            except Exception:
                pass
            self._cold_conn = None
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        self.conn.close()


class _PriorRevisionWatcher(FileWatcher):
    """Real watcher with the old restartable, silent-timeout shutdown."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.legacy_stop_calls = 0
        self.legacy_start_calls = 0

    def start(self) -> None:
        if not self._config.enabled:
            return
        self.legacy_start_calls += 1
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="prior-engram-watcher"
        )
        self._consumer_thread = threading.Thread(
            target=self._consume_loop, daemon=True, name="prior-engram-consumer"
        )
        self._watcher_thread.start()
        self._consumer_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.legacy_stop_calls += 1
        self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=timeout)
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=timeout)

    def _index_file_unlocked(self, path):
        before_index = getattr(self, "_before_index", None)
        if before_index is not None:
            before_index(path)
        return super()._index_file_unlocked(path)


class _PriorRevisionCompiler(CategoryCompiler):
    """The b9 waiter loop, which ignores `_closing` after a wakeup."""

    def _acquire_compile_connection(self, deadline: int) -> sqlite3.Connection:
        self._assert_database_identity()
        with self._pool_condition:
            if self._closed or self._closing:
                raise RuntimeError("category compiler is closed")
            while not self._available_connections:
                if self._closed:
                    raise RuntimeError("category compiler is closed")
                remaining_ns = deadline - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise _DeadlineExceeded
                self._pool_condition.wait(remaining_ns / 1_000_000_000)
            if self._closed or self._closing:
                raise RuntimeError("category compiler is closed")
            if time.monotonic_ns() >= deadline:
                raise _DeadlineExceeded
            connection = self._available_connections.pop()
            self._leased_connections[connection] = threading.get_ident()
        try:
            self._assert_database_identity()
            if time.monotonic_ns() >= deadline:
                raise _DeadlineExceeded
        except Exception:
            self._release_compile_connection(connection)
            raise
        return connection


class _PriorRevisionObserver(CategoryObserver):
    """Concrete prior-generation observer owning a prior compiler pool."""


class _PriorRevisionKnowledgeGraph(KnowledgeGraph):
    """Concrete KG owner with the old swallowed graph-close failure."""

    def close(self):
        if self._graphiti is not None:
            try:
                self._run_async(self._graphiti.close())
            except Exception:
                pass
        self._shutdown_executor()


class _ObservedCompilerCondition(threading.Condition):
    def __init__(self, compiler):
        super().__init__()
        self.compiler = compiler
        self.waiter_ident = None
        self.waiting = threading.Event()
        self.shutdown_started = threading.Event()

    def wait(self, timeout=None):
        if threading.get_ident() == self.waiter_ident:
            self.waiting.set()
        return super().wait(timeout)

    def notify_all(self):
        if self.compiler._closed or self.compiler._closing:
            self.shutdown_started.set()
        return super().notify_all()


def _make_prior_observer(path):
    observer = _PriorRevisionObserver(path)
    observer.compiler.close()
    observer.compiler = _PriorRevisionCompiler(
        observer.store, observer._compile_budget
    )
    condition = _ObservedCompilerCondition(observer.compiler)
    observer.compiler._pool_condition = condition
    return observer, condition


def _prior_cleanup_callback(resource, cleanup, label):
    """Match b9 exact callbacks, including their fail-soft wrapper."""
    completed = False
    callback_lock = threading.Lock()

    def callback():
        nonlocal completed
        with callback_lock:
            if completed:
                return
            try:
                cleanup()
            except Exception:
                return
            completed = True

    callback._server_resource = resource
    callback._server_cleanup_label = label
    return callback


def _prior_category_callback(observer):
    def callback():
        try:
            observer.close()
        except Exception:
            pass

    callback._category_observer = observer
    return callback


def _reload_config(tmp_path, *, watcher=True, category=True):
    from config import load_config

    config = load_config(tmp_path)
    config.graph.enabled = False
    config.watcher.enabled = watcher
    config.category_evolution.enabled = category
    config.category_evolution.shadow = True
    config.category_evolution.influence_recall = False
    config.category_evolution.auto_commit = False
    config.category_evolution.db_path = ""
    return config


def _install_prior_server_generation(
    monkeypatch,
    tmp_path,
    *,
    storage,
    watcher,
    knowledge_graph,
    category_store,
    observer,
    config,
    lifecycle,
    embedding_factory=FakeEmbeddingProvider,
):
    for callback in tuple(getattr(server, "_server_atexit_callbacks", ())):
        atexit.unregister(callback)
    category_callback = getattr(server, "_category_atexit_callback", None)
    if category_callback is not None:
        atexit.unregister(category_callback)

    registered = []

    def unregister(callback):
        registered[:] = [item for item in registered if item is not callback]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    monkeypatch.setattr("config.load_config", lambda _root: config)
    monkeypatch.setattr("embeddings.NomicEmbedProvider", embedding_factory)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setenv("ENGRAM_PROJECT_ROOT", str(tmp_path))

    callbacks = [
        _prior_cleanup_callback(watcher, watcher.stop, "watcher"),
        _prior_cleanup_callback(storage, storage.close, "storage"),
        _prior_cleanup_callback(
            knowledge_graph, knowledge_graph.close, "knowledge graph"
        ),
        _prior_cleanup_callback(
            category_store._conn, category_store._conn.close, "category store"
        ),
    ]
    observer_callback = _prior_category_callback(observer) if observer else None
    registered.extend(callbacks)
    if observer_callback is not None:
        registered.append(observer_callback)

    values = {
        "_storage": storage,
        "_embeddings": watcher._embedding_provider,
        "_config": config,
        "_compressor": object(),
        "_reflector": None,
        "_watcher": watcher,
        "_session_id": "prior-session",
        "_session_episode_count": 0,
        "_instance_name": None,
        "_initialized": True,
        "_genome_db_path": None,
        "_signals_db_path": None,
        "_knowledge_graph": knowledge_graph,
        "_category_store": category_store,
        "_category_observer": observer,
        "_category_pending_close": None,
        "_category_status": None,
        "_category_atexit_callback": observer_callback,
        "_category_last_observed_at": None,
        "_clipboard": None,
        "_instinct_graph": None,
        "_notepad_project": None,
        "_notepad_global": None,
        "_server_lifecycle_lock": lifecycle,
        "_init_lock": threading.RLock(),
        "_category_recall_lock": threading.RLock(),
        "_server_pid_guard": threading.RLock(),
        "_server_lock_pid": os.getpid(),
        "_server_atexit_callbacks": callbacks,
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_session_id": None,
        "_fork_quarantined_resources": [],
        "_SERVER_AT_FORK_REGISTERED": True,
        "_SERVER_AT_FORK_LIFECYCLE_VERSION": 2,
        "_LEGACY_DYNAMIC_ATEXIT_REQUIRED": False,
        "_legacy_dynamic_atexit_guard": None,
    }
    for name, value in values.items():
        monkeypatch.setattr(server, name, value, raising=False)
    return registered


def _make_prior_knowledge_graph(*, fail_graph_once=False):
    class GraphHandle:
        def __init__(self):
            self.close_attempts = 0

        def close(self):
            self.close_attempts += 1
            return self

    class ExecutorHandle:
        def __init__(self):
            self.shutdown_attempts = 0

        def shutdown(self, *, wait):
            assert wait is False
            self.shutdown_attempts += 1

    graph = GraphHandle()
    executor = ExecutorHandle()
    knowledge = _PriorRevisionKnowledgeGraph.__new__(
        _PriorRevisionKnowledgeGraph
    )
    knowledge._graphiti = graph
    knowledge._executor = executor

    def run_async(handle):
        assert handle is graph
        if fail_graph_once and graph.close_attempts == 1:
            raise RuntimeError("private prior graph close detail")

    knowledge._run_async = run_async
    return knowledge, graph, executor


def test_incompatible_reload_retires_real_prior_generation_before_rebuild(
    tmp_path, monkeypatch
):
    """An unmarked live generation is quiesced and rebuilt, never adopted."""
    config = _reload_config(tmp_path)
    lifecycle = _ObservedRLock()
    index_entered = threading.Event()
    allow_index = threading.Event()

    old_storage = _PriorRevisionStorage(str(tmp_path / "prior-graph.db"))
    old_embedding = FakeEmbeddingProvider()
    old_watcher = _PriorRevisionWatcher(
        tmp_path,
        config.watcher,
        old_storage,
        old_embedding,
        operation_lock=lifecycle,
    )

    def block_prior_index(path):
        if path.name == "prior_blocked.py":
            index_entered.set()
            assert allow_index.wait(timeout=5)

    old_watcher._before_index = block_prior_index
    old_observer, compiler_condition = _make_prior_observer(
        tmp_path / "prior-categories-v2.db"
    )
    old_compiler = old_observer.compiler
    old_knowledge, old_graph, old_executor = _make_prior_knowledge_graph()
    old_category_connection = sqlite3.connect(tmp_path / "prior-categories.db")
    old_category_store = type(
        "PriorCategoryStore", (), {"_conn": old_category_connection}
    )()
    registered = _install_prior_server_generation(
        monkeypatch,
        tmp_path,
        storage=old_storage,
        watcher=old_watcher,
        knowledge_graph=old_knowledge,
        category_store=old_category_store,
        observer=old_observer,
        config=config,
        lifecycle=lifecycle,
    )

    source = tmp_path / "prior_blocked.py"
    source.write_text("def prior_blocked():\n    return 1\n")
    old_watcher.start()
    old_watcher._queue.put(source)
    assert index_entered.wait(timeout=5)

    leased = []
    leases_ready = threading.Event()
    release_leases = threading.Event()
    borrower_errors = []

    def borrow_prior_compiler_connections():
        try:
            for _ in range(len(old_compiler._available_connections)):
                leased.append(
                    old_compiler._acquire_compile_connection(10**30)
                )
            leases_ready.set()
            assert release_leases.wait(timeout=5)
            for connection in leased:
                if connection in old_compiler._leased_connections:
                    old_compiler._release_compile_connection(connection)
        except Exception as exc:
            borrower_errors.append(exc)

    borrower = threading.Thread(target=borrow_prior_compiler_connections)
    borrower.start()
    assert leases_ready.wait(timeout=5)
    waiter_finished = threading.Event()
    waiter_errors = []

    def wait_for_prior_compiler():
        compiler_condition.waiter_ident = threading.get_ident()
        try:
            old_compiler._acquire_compile_connection(
                time.monotonic_ns() + 5_000_000_000
            )
        except Exception as exc:
            waiter_errors.append(exc)
        finally:
            waiter_finished.set()

    waiter = threading.Thread(target=wait_for_prior_compiler)
    waiter.start()
    assert compiler_condition.waiting.wait(timeout=5)

    reload_returned = threading.Event()
    release_observations = []
    replacement_coordinator = None

    def unblock_retirement():
        stop_started = old_watcher._stop_event.wait(timeout=2)
        release_observations.append(
            (stop_started, old_watcher.is_alive(), reload_returned.is_set())
        )
        allow_index.set()
        shutdown_started = compiler_condition.shutdown_started.wait(timeout=2)
        rejected_while_closing = waiter_finished.wait(timeout=0.25)
        release_observations.append(
            (shutdown_started, rejected_while_closing, reload_returned.is_set())
        )
        release_leases.set()

    releaser = threading.Thread(target=unblock_retirement)
    releaser.start()
    try:
        reloaded = importlib.reload(server)
        replacement_coordinator = getattr(
            reloaded, "_server_generation_cleanup", None
        )
        reload_returned.set()
        releaser.join(timeout=5)
        borrower.join(timeout=5)
        waiter.join(timeout=5)

        assert release_observations == [
            (True, True, False),
            (True, True, False),
        ]
        assert len(waiter_errors) == 1
        assert isinstance(waiter_errors[0], RuntimeError)
        assert borrower_errors == []
        assert old_watcher.is_alive() is False
        assert old_watcher.legacy_stop_calls == 1
        assert old_storage.legacy_close_calls == 0
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            old_storage.conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            old_category_connection.execute("SELECT 1")
        assert old_observer._closed is True
        assert old_observer.compiler is None
        assert old_observer.store is None
        assert old_graph.close_attempts == 1
        assert old_executor.shutdown_attempts == 1
        assert old_knowledge._graphiti is None
        assert old_knowledge._executor is None

        coordinator = reloaded._server_generation_cleanup
        assert reloaded._initialized is True
        assert reloaded._session_id == "prior-session"
        assert reloaded._storage is not old_storage
        assert reloaded._watcher is not old_watcher
        assert reloaded._category_observer is not old_observer
        assert reloaded._storage._check_same_thread is False
        assert coordinator._resource_lifecycle_abi == (
            reloaded._SERVER_RESOURCE_LIFECYCLE_ABI
        )
        assert old_storage not in coordinator._server_resources
        assert reloaded._category_atexit_callback is coordinator
        assert registered == [coordinator]

        current_source = tmp_path / "current_worker.py"
        current_source.write_text("def current_worker():\n    return 2\n")
        indexing_finished = threading.Event()
        indexing_errors = []

        def index_with_current_storage():
            try:
                reloaded._watcher._index_file(current_source)
            except Exception as exc:
                indexing_errors.append(exc)
            finally:
                indexing_finished.set()

        current_worker = threading.Thread(target=index_with_current_storage)
        current_worker.start()
        assert indexing_finished.wait(timeout=5)
        current_worker.join(timeout=5)
        assert indexing_errors == []
        assert reloaded._storage.get_entity(
            "symbol:current_worker.py::current_worker"
        ) is not None

        current_compiler = reloaded._category_observer.compiler
        current_condition = _ObservedCompilerCondition(current_compiler)
        current_compiler._pool_condition = current_condition
        current_leased = [
            current_compiler._acquire_compile_connection(10**30)
            for _ in range(len(current_compiler._available_connections))
        ]
        current_waiter_finished = threading.Event()
        current_waiter_errors = []

        def wait_for_current_compiler():
            current_condition.waiter_ident = threading.get_ident()
            try:
                current_compiler._acquire_compile_connection(
                    time.monotonic_ns() + 500_000_000
                )
            except Exception as exc:
                current_waiter_errors.append(exc)
            finally:
                current_waiter_finished.set()

        current_waiter = threading.Thread(target=wait_for_current_compiler)
        current_waiter.start()
        assert current_condition.waiting.wait(timeout=5)
        close_finished = threading.Event()
        close_errors = []

        def close_current_compiler():
            try:
                current_compiler.close()
            except Exception as exc:
                close_errors.append(exc)
            finally:
                close_finished.set()

        current_closer = threading.Thread(target=close_current_compiler)
        current_closer.start()
        assert current_condition.shutdown_started.wait(timeout=5)
        assert current_waiter_finished.wait(timeout=0.25)
        assert close_finished.is_set() is False
        for connection in current_leased:
            current_compiler._release_compile_connection(connection)
        assert close_finished.wait(timeout=5)
        current_waiter.join(timeout=5)
        current_closer.join(timeout=5)
        assert len(current_waiter_errors) == 1
        assert isinstance(current_waiter_errors[0], RuntimeError)
        assert close_errors == []

        for callback in reversed(tuple(registered)):
            callback()
        for callback in reversed(tuple(registered)):
            callback()
        assert reloaded._watcher.is_alive() is False
        reloaded._watcher.start()
        assert reloaded._watcher.is_alive() is False
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            reloaded._storage.conn.execute("SELECT 1")
    finally:
        if replacement_coordinator is not None:
            replacement_coordinator()
        release_leases.set()
        allow_index.set()
        for connection in tuple(old_compiler._leased_connections):
            old_compiler._release_compile_connection(connection)
        releaser.join(timeout=5)
        borrower.join(timeout=5)
        waiter.join(timeout=5)
        if old_watcher.is_alive():
            old_watcher.stop()
        if not old_observer._closed:
            old_observer.close()
        try:
            old_category_connection.close()
        except Exception:
            pass
        try:
            old_storage.close()
        except Exception:
            pass


def test_failed_legacy_retirement_is_type_only_and_retried_before_rebuild(
    tmp_path, monkeypatch
):
    """Failed native handles stay exact and block replacement until `_init`."""
    config = _reload_config(tmp_path, watcher=False, category=False)
    lifecycle = _ObservedRLock()
    constructions = []

    class CountingEmbedding(FakeEmbeddingProvider):
        def __init__(self):
            constructions.append("embedding")
            super().__init__()

    class FailOnceColdConnection:
        def __init__(self):
            self.close_attempts = 0

        def close(self):
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise sqlite3.OperationalError(
                    "private prior cold close detail"
                )

    old_storage = _PriorRevisionStorage(str(tmp_path / "prior-failure.db"))
    cold_connection = FailOnceColdConnection()
    old_storage._cold_conn = cold_connection
    old_embedding = FakeEmbeddingProvider()
    old_watcher = _PriorRevisionWatcher(
        tmp_path,
        config.watcher,
        old_storage,
        old_embedding,
        operation_lock=lifecycle,
    )
    old_knowledge, old_graph, old_executor = _make_prior_knowledge_graph(
        fail_graph_once=True
    )
    old_category_connection = sqlite3.connect(
        tmp_path / "prior-failure-categories.db"
    )
    old_category_store = type(
        "PriorCategoryStore", (), {"_conn": old_category_connection}
    )()
    registered = _install_prior_server_generation(
        monkeypatch,
        tmp_path,
        storage=old_storage,
        watcher=old_watcher,
        knowledge_graph=old_knowledge,
        category_store=old_category_store,
        observer=None,
        config=config,
        lifecycle=lifecycle,
        embedding_factory=CountingEmbedding,
    )
    old_compressor = server._compressor

    reloaded = importlib.reload(server)

    assert reloaded._initialized is False
    assert reloaded._storage is None
    assert reloaded._watcher is None
    assert reloaded._knowledge_graph is None
    assert constructions == []
    assert reloaded._server_lifecycle_status == {
        "available": False,
        "error": "RuntimeError",
        "last_error": "RuntimeError",
    }
    assert "private" not in str(reloaded._server_lifecycle_status)
    pending = reloaded._server_pending_retirement
    assert pending is not None
    assert old_storage in pending._server_resources
    assert old_knowledge in pending._server_resources
    assert cold_connection.close_attempts == 1
    assert old_storage._cold_conn is cold_connection
    assert old_graph.close_attempts == 1
    assert old_knowledge._graphiti is old_graph
    assert old_executor.shutdown_attempts == 1
    assert old_knowledge._executor is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        old_storage.conn.execute("SELECT 1")
    assert registered == [pending]

    # A fork while retirement is pending must quarantine the complete exact
    # generation, including owners that never had their own callback.  The
    # child must not retry or destruct inherited native state.
    old_embedding = old_watcher._embedding_provider
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            quarantined = reloaded._fork_quarantined_resources
            clean = (
                reloaded._server_pending_retirement is None
                and reloaded._storage is None
                and old_storage in quarantined
                and old_embedding in quarantined
                and old_compressor in quarantined
                and cold_connection.close_attempts == 1
                and old_graph.close_attempts == 1
            )
            os.write(write_fd, b"clean" if clean else b"dirty")
            os._exit(0 if clean else 2)
        except BaseException:
            os._exit(3)

    os.close(write_fd)
    payload, status = _wait_for_child(pid, read_fd)
    os.close(read_fd)
    assert payload == b"clean"
    assert os.waitstatus_to_exitcode(status) == 0
    assert reloaded._server_pending_retirement is pending
    assert cold_connection.close_attempts == 1
    assert old_graph.close_attempts == 1

    reloaded._init()

    assert cold_connection.close_attempts == 2
    assert old_storage._cold_conn is None
    assert old_graph.close_attempts == 2
    assert old_knowledge._graphiti is None
    assert old_executor.shutdown_attempts == 1
    assert reloaded._server_pending_retirement is None
    assert reloaded._server_lifecycle_status is None
    assert reloaded._initialized is True
    assert constructions == ["embedding"]
    assert reloaded._storage is not old_storage
    coordinator = reloaded._server_generation_cleanup
    assert coordinator._resource_lifecycle_abi == (
        reloaded._SERVER_RESOURCE_LIFECYCLE_ABI
    )
    assert registered == [coordinator]

    for callback in reversed(tuple(registered)):
        callback()


def test_compatible_reload_preserves_exact_generation_without_duplicate_callback(
    tmp_path, monkeypatch
):
    """A matching generation ABI preserves owners, workers, and one callback."""
    import watcher as watcher_module

    config = _reload_config(tmp_path)
    for callback in tuple(getattr(server, "_server_atexit_callbacks", ())):
        atexit.unregister(callback)
    registered = []
    unregistered = []
    starts = []
    stops = []
    current_watcher_class = watcher_module.FileWatcher
    real_start = current_watcher_class.start
    real_stop = current_watcher_class.stop

    def observed_start(watcher):
        starts.append(watcher)
        return real_start(watcher)

    def observed_stop(watcher, *args, **kwargs):
        stops.append(watcher)
        return real_stop(watcher, *args, **kwargs)

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    monkeypatch.setattr(current_watcher_class, "start", observed_start)
    monkeypatch.setattr(current_watcher_class, "stop", observed_stop)
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "DB_PATH", tmp_path / ".engram" / "graph.db")
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
        "_knowledge_graph": None,
        "_category_store": None,
        "_category_observer": None,
        "_category_pending_close": None,
        "_category_status": None,
        "_category_atexit_callback": None,
        "_clipboard": None,
        "_server_atexit_callbacks": [],
        "_server_generation_cleanup": None,
        "_server_pending_retirement": None,
        "_server_lifecycle_status": None,
        "_server_reload_session_id": None,
        "_server_lock_pid": os.getpid(),
    }.items():
        monkeypatch.setattr(server, name, value, raising=False)

    server._init()
    abi = server._SERVER_RESOURCE_LIFECYCLE_ABI
    storage = server._storage
    watcher = server._watcher
    observer = server._category_observer
    coordinator = server._server_generation_cleanup
    watcher.start()
    watcher_threads = (watcher._watcher_thread, watcher._consumer_thread)
    callbacks = tuple(registered)
    # The callback owns the ABI.  A reload can recover the convenience global
    # from that exact marked owner without constructing or registering another.
    server._server_generation_cleanup = None

    reloaded = importlib.reload(server)
    reloaded._init()

    try:
        assert reloaded._storage is storage
        assert reloaded._watcher is watcher
        assert reloaded._category_observer is observer
        assert reloaded._server_generation_cleanup is coordinator
        assert reloaded._server_atexit_callbacks == [coordinator]
        assert reloaded._category_atexit_callback is coordinator
        assert coordinator._resource_lifecycle_abi == abi
        assert tuple(registered) == callbacks == (coordinator,)
        assert unregistered == []
        assert starts == [watcher]
        assert stops == []
        assert (watcher._watcher_thread, watcher._consumer_thread) == (
            watcher_threads
        )
        assert watcher.is_alive() is True
    finally:
        coordinator()


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
    monkeypatch.setattr(server, "_server_pending_retirement", None, raising=False)
    monkeypatch.setattr(server, "_server_lock_pid", os.getpid())
    monkeypatch.setattr(
        server,
        "_init_unlocked",
        lambda: storage.conn.execute("SELECT 1").fetchone()[0],
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
