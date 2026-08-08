import time
import threading
from pathlib import Path
import pytest
from watcher import FileWatcher
from config import WatcherConfig


def test_watcher_start_stop(tmp_path):
    """Watcher starts and stops cleanly."""
    config = WatcherConfig(enabled=True, debounce_ms=100)
    watcher = FileWatcher(tmp_path, config, storage=None, embedding_provider=None)
    watcher.start()
    assert watcher.is_alive()
    watcher.stop(timeout=2.0)
    assert not watcher.is_alive()


def test_watcher_cannot_restart_after_shutdown_begins(tmp_path):
    """Cleanup stop is terminal so lifecycle drain cannot spawn new workers."""
    config = WatcherConfig(enabled=True, debounce_ms=100)
    watcher = FileWatcher(tmp_path, config, storage=None, embedding_provider=None)

    watcher.start()
    watcher.stop(timeout=2.0)
    watcher.start()

    try:
        assert watcher.is_alive() is False
    finally:
        if watcher.is_alive():
            watcher.stop(timeout=2.0)


def test_watcher_not_started_when_disabled(tmp_path):
    config = WatcherConfig(enabled=False)
    watcher = FileWatcher(tmp_path, config, storage=None, embedding_provider=None)
    watcher.start()
    assert not watcher.is_alive()


def test_watcher_should_index_filters_extensions(tmp_path):
    """Only configured extensions pass the filter."""
    config = WatcherConfig(extensions=[".py", ".ts"])
    watcher = FileWatcher(tmp_path, config, storage=None, embedding_provider=None)
    assert watcher._should_index(tmp_path / "foo.py")
    assert watcher._should_index(tmp_path / "bar.ts")
    assert not watcher._should_index(tmp_path / "readme.md")
    assert not watcher._should_index(tmp_path / "data.json")


def test_watcher_should_index_excludes_directories(tmp_path):
    """Excluded directories are filtered out."""
    config = WatcherConfig(extensions=[".py"])
    watcher = FileWatcher(tmp_path, config, storage=None, embedding_provider=None)
    assert not watcher._should_index(tmp_path / "node_modules" / "pkg" / "index.py")
    assert not watcher._should_index(tmp_path / ".venv" / "lib" / "foo.py")
    assert not watcher._should_index(tmp_path / ".git" / "hooks" / "pre-commit.py")
    assert watcher._should_index(tmp_path / "src" / "main.py")


def test_watcher_indexing_participates_in_server_lifecycle_barrier(
    tmp_path, monkeypatch
):
    """Background SQLite indexing cannot cross a held fork lifecycle lock."""
    lifecycle = threading.RLock()
    index_entered = threading.Event()
    finished = threading.Event()
    config = WatcherConfig(extensions=[".py"])
    watcher = FileWatcher(
        tmp_path,
        config,
        storage=object(),
        embedding_provider=object(),
        operation_lock=lifecycle,
    )
    monkeypatch.setattr(
        "indexer.index_file", lambda *_args, **_kwargs: index_entered.set()
    )
    lifecycle.acquire()
    worker = threading.Thread(
        target=lambda: (watcher._index_file(tmp_path / "module.py"), finished.set())
    )
    worker.start()
    try:
        assert index_entered.wait(timeout=0.1) is False
    finally:
        lifecycle.release()
    assert finished.wait(timeout=5)
    worker.join(timeout=5)
    assert index_entered.is_set()
