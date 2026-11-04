"""Another checkout inside the project is never indexed, and the watcher
honours the configured excludes (the Pi, 2026-11-04: 106 worktrees under
.worktrees/ were re-embedded on every edit, keeping the shared embedder busy)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import WatcherConfig
from indexer import full_reindex
from watcher import FileWatcher


def _tree(root: Path) -> None:
    for rel in (
        "src/a.py",
        "generated/g.py",
        ".worktrees/other/src/a.py",
        "vendor/lib/x.py",
        ".claude/worktrees/w/src/a.py",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def f():\n    return 1\n")
    # A git worktree or submodule marks its top with a .git file.
    (root / "vendor/lib/.git").write_text("gitdir: elsewhere\n")
    (root / ".claude/worktrees/w/.git").write_text("gitdir: elsewhere\n")


def _watcher(root: Path, exclude=None) -> FileWatcher:
    return FileWatcher(
        root, WatcherConfig(extensions=[".py"]), storage=None,
        embedding_provider=None, exclude=exclude,
    )


def test_watcher_honours_the_configured_exclude(tmp_path):
    _tree(tmp_path)
    watcher = _watcher(tmp_path, exclude=["generated"])
    assert not watcher._should_index(tmp_path / "generated/g.py")
    assert watcher._should_index(tmp_path / "src/a.py")


def test_watcher_never_indexes_another_checkout(tmp_path):
    _tree(tmp_path)
    watcher = _watcher(tmp_path, exclude=["node_modules"])
    assert not watcher._should_index(tmp_path / ".worktrees/other/src/a.py")
    assert not watcher._should_index(tmp_path / "vendor/lib/x.py")
    assert not watcher._should_index(tmp_path / ".claude/worktrees/w/src/a.py")
    assert watcher._should_index(tmp_path / "src/a.py")


def test_watcher_reads_only_the_parts_below_its_root(tmp_path):
    root = tmp_path / "build" / "project"
    _tree(root)
    watcher = _watcher(root)
    assert watcher._should_index(root / "src/a.py")
    assert not watcher._should_index(tmp_path / "elsewhere.py")


def test_server_hands_the_watcher_the_indexing_excludes():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text()
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "FileWatcher"
    ]
    assert calls, "server.py builds no FileWatcher"
    for call in calls:
        exclude = [k for k in call.keywords if k.arg == "exclude"]
        assert exclude, "FileWatcher built without exclude="
        assert ast.unparse(exclude[0].value) == "_config.indexing.exclude"


def test_full_reindex_skips_other_checkouts_and_configured_dirs(tmp_path):
    _tree(tmp_path)
    config = SimpleNamespace(indexing=SimpleNamespace(exclude=["generated"]))
    seen = []
    with patch("indexer.index_file",
               lambda _s, _e, path, _lang, root: seen.append(path.relative_to(root))), \
         patch("indexer._get_current_commit", lambda _root: None):
        count = full_reindex(object(), object(), tmp_path, config)
    assert seen == [Path("src/a.py")]
    assert count == 1
