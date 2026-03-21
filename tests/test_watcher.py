import time
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
