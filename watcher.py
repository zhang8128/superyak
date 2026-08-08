"""Background file watcher using watchfiles for incremental code indexing."""
from __future__ import annotations

import logging
from pathlib import Path
from queue import SimpleQueue, Empty
from threading import Thread, Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import WatcherConfig
    from storage import Storage

logger = logging.getLogger("engram.watcher")

_DEFAULT_EXCLUDE = {"node_modules", ".venv", "__pycache__", "dist", "build"}


class FileWatcher:
    def __init__(self, project_root: Path, config: "WatcherConfig",
                 storage: "Storage | None", embedding_provider: object | None,
                 operation_lock: object | None = None):
        self._root = project_root
        self._config = config
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._operation_lock = operation_lock
        self._queue: SimpleQueue[Path] = SimpleQueue()
        self._stop_event = Event()
        self._watcher_thread: Thread | None = None
        self._consumer_thread: Thread | None = None
        self._processed = 0
        self._extensions = set(config.extensions)
        self._exclude_dirs = set(getattr(config, 'exclude', None) or _DEFAULT_EXCLUDE)

    def start(self) -> None:
        if not self._config.enabled:
            logger.info("watcher disabled by config")
            return
        self._stop_event.clear()
        self._watcher_thread = Thread(target=self._watch_loop, daemon=True, name="engram-watcher")
        self._consumer_thread = Thread(target=self._consume_loop, daemon=True, name="engram-consumer")
        self._watcher_thread.start()
        self._consumer_thread.start()
        logger.info("file watcher started for %s (extensions: %s)", self._root, self._extensions)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=timeout)
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=timeout)
        logger.info("file watcher stopped (processed %d files)", self._processed)

    def is_alive(self) -> bool:
        return (self._watcher_thread is not None and self._watcher_thread.is_alive()
                and self._consumer_thread is not None and self._consumer_thread.is_alive())

    def pending_count(self) -> int:
        return self._queue.qsize()

    def processed_count(self) -> int:
        return self._processed

    def _should_index(self, path: Path) -> bool:
        if ".git" in path.parts:
            return False
        if path.suffix not in self._extensions:
            return False
        for part in path.parts:
            if part in self._exclude_dirs:
                return False
        return True

    def _watch_loop(self) -> None:
        try:
            from watchfiles import watch
            for changes in watch(self._root, stop_event=self._stop_event,
                                 debounce=self._config.debounce_ms, step=50):
                for change_type, path_str in changes:
                    path = Path(path_str)
                    if self._should_index(path):
                        self._queue.put(path)
                        logger.debug("queued %s (%s)", path.name, change_type)
        except Exception:
            logger.error("watcher thread crashed", exc_info=True)

    def _consume_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                path = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._index_file(path)
                self._processed += 1
            except Exception:
                logger.error("failed to index %s", path, exc_info=True)

    def _index_file(self, path: Path) -> None:
        if self._operation_lock is not None:
            with self._operation_lock:
                self._index_file_unlocked(path)
            return
        self._index_file_unlocked(path)

    def _index_file_unlocked(self, path: Path) -> None:
        if self._storage is None or self._embedding_provider is None:
            return
        from indexer import index_file
        ext_to_lang = {".py": "python", ".js": "javascript", ".ts": "typescript",
                       ".tsx": "typescript", ".rs": "rust", ".go": "go"}
        lang = ext_to_lang.get(path.suffix)
        if lang:
            index_file(self._storage, self._embedding_provider, path, lang, self._root)
            logger.debug("indexed %s (%s)", path.relative_to(self._root), lang)
