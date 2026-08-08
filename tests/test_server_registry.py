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

import pytest

import server


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
    """Reload adopts exact owners into one callback without replacing its lock."""
    class Resource:
        def close(self):
            pass

    resource = Resource()
    project_notepad = Resource()
    global_notepad = Resource()
    callback = server._make_server_cleanup(
        resource, resource.close, "storage"
    )
    registered = [callback]

    def unregister(item):
        registered[:] = [callback for callback in registered if callback is not item]

    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregister)
    lifecycle = threading.RLock()
    monkeypatch.setattr(server, "_storage", resource)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle, raising=False)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [callback], raising=False)
    monkeypatch.setattr(server, "_notepad_project", project_notepad)
    monkeypatch.setattr(server, "_notepad_global", global_notepad)

    reloaded = importlib.reload(server)

    assert reloaded._storage is resource
    assert reloaded._initialized is True
    assert reloaded._server_lifecycle_lock is lifecycle
    assert len(reloaded._server_atexit_callbacks) == 1
    coordinator = reloaded._server_atexit_callbacks[0]
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
    registered = [coordinator]
    unregistered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    monkeypatch.setattr(atexit, "unregister", unregistered.append)
    monkeypatch.setattr(server, "_server_lifecycle_lock", lifecycle)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [coordinator])
    monkeypatch.setattr(server, "_server_generation_cleanup", coordinator)
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


def test_reload_migration_masks_legacy_dynamic_atexit_callbacks_after_fork(
    monkeypatch,
):
    """Base callbacks cannot double-close a child generation after upgrade."""
    class Resource:
        def __init__(self):
            self.close_count = 0

        def close(self):
            self.close_count += 1

        def stop(self):
            self.close()

    old_storage = Resource()
    old_watcher = Resource()
    old_knowledge = Resource()
    old_category_connection = Resource()
    old_category_store = type(
        "CategoryStore", (), {"_conn": old_category_connection}
    )()
    old_clipboard = Resource()
    old_instinct_graph = Resource()
    old_project_notepad = Resource()
    old_global_notepad = Resource()
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
    monkeypatch.setattr(server, "_storage", old_storage)
    monkeypatch.setattr(server, "_watcher", old_watcher)
    monkeypatch.setattr(server, "_knowledge_graph", old_knowledge)
    monkeypatch.setattr(server, "_category_store", old_category_store)
    monkeypatch.setattr(server, "_clipboard", old_clipboard)
    monkeypatch.setattr(server, "_instinct_graph", old_instinct_graph)
    monkeypatch.setattr(server, "_notepad_project", old_project_notepad)
    monkeypatch.setattr(server, "_notepad_global", old_global_notepad)
    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_server_atexit_callbacks", [])
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

    coordinators = [
        callback
        for callback in registered
        if getattr(callback, "_server_cleanup_coordinator", False)
    ]
    assert len(coordinators) == 1
    adopted = set(coordinators[0]._server_resources)
    assert adopted == {
        old_watcher,
        old_storage,
        old_knowledge,
        old_category_connection,
        old_clipboard,
        old_instinct_graph,
        old_project_notepad,
        old_global_notepad,
    }

    resources = reloaded._server_owned_resources()
    reloaded._reset_server_child_state(resources, os.getpid())
    child_storage = Resource()
    reloaded._storage = child_storage
    reloaded._register_server_cleanup(
        child_storage, child_storage.close, "storage"
    )

    for callback in reversed(tuple(registered)):
        callback()

    assert old_storage in reloaded._fork_quarantined_resources
    assert all(
        resource.close_count == 0
        for resource in (
            old_storage,
            old_watcher,
            old_knowledge,
            old_category_connection,
            old_clipboard,
            old_instinct_graph,
            old_project_notepad,
            old_global_notepad,
        )
    )
    assert child_storage.close_count == 1
