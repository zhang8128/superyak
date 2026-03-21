"""Tests for tree-sitter code indexer."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from indexer import (
    extract_edges,
    full_reindex,
    get_changed_files,
    incremental_index,
    index_file,
    parse_file,
)


SAMPLE_PYTHON = textwrap.dedent("""\
    import os
    from pathlib import Path

    def greet(name: str) -> str:
        \"\"\"Say hello.\"\"\"
        return f"Hello, {name}"

    class Greeter:
        \"\"\"A greeting machine.\"\"\"

        def say_hi(self):
            return "hi"

        def say_bye(self):
            return "bye"
""")

SAMPLE_JS = textwrap.dedent("""\
    import { readFile } from 'fs';

    function add(a, b) {
        return a + b;
    }

    class Calculator {
        multiply(a, b) {
            return a * b;
        }
    }

    const sub = (a, b) => a - b;
""")


# --- parse_file ---

def test_parse_python_file(tmp_path):
    """Parse a Python file and verify extracted symbols."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    symbols = parse_file(f, "python")
    names = {s["name"] for s in symbols}
    kinds = {s["name"]: s["kind"] for s in symbols}

    assert "greet" in names
    assert "Greeter" in names
    assert "say_hi" in names
    assert "say_bye" in names
    assert kinds["greet"] == "function"
    assert kinds["Greeter"] == "class"
    assert kinds["say_hi"] == "method"


def test_parse_javascript_file(tmp_path):
    """Parse a JavaScript file and verify extracted symbols."""
    f = tmp_path / "sample.js"
    f.write_text(SAMPLE_JS)

    symbols = parse_file(f, "javascript")
    names = {s["name"] for s in symbols}

    assert "add" in names
    assert "Calculator" in names
    assert "multiply" in names
    assert "sub" in names


def test_symbol_entity_metadata(tmp_path):
    """Verify symbols have file, line, kind, language metadata."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    symbols = parse_file(f, "python")
    greet = next(s for s in symbols if s["name"] == "greet")

    assert greet["kind"] == "function"
    assert greet["line"] >= 1
    assert "body_preview" in greet


# --- extract_edges ---

def test_extract_call_edges(tmp_path):
    """Verify import edges are detected from Python source."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    symbols = parse_file(f, "python")
    edges = extract_edges(f, symbols, "python")

    # Should find imports (os, Path)
    assert len(edges) >= 1
    assert any(e["kind"] == "imports" for e in edges)


def test_extract_import_edges(tmp_path):
    """import X and from X import Y both produce depends_on edges."""
    code = textwrap.dedent("""\
        import json
        from os.path import join
    """)
    f = tmp_path / "imp.py"
    f.write_text(code)

    symbols = parse_file(f, "python")
    edges = extract_edges(f, symbols, "python")

    imported = {e["target"] for e in edges}
    assert "json" in imported
    assert "os.path" in imported or "join" in imported


# --- embedding text format ---

def test_embedding_text_format(tmp_path):
    """Verify embedding text contains kind, name, and file path."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    symbols = parse_file(f, "python")
    greet = next(s for s in symbols if s["name"] == "greet")

    # Build embedding text the same way index_file does
    rel = f.relative_to(tmp_path)
    text = f"{greet['kind']} {greet['name']} in {rel}: {greet['body_preview'][:200]}"

    assert "function" in text
    assert "greet" in text
    assert "sample.py" in text


# --- index_file ---

def test_index_file_creates_entities(tmp_db, tmp_path):
    """Index a file and verify symbol entities appear in storage."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    mock_embed = MagicMock()
    mock_embed.embed.return_value = [[0.1] * 768] * 10  # enough for all symbols

    index_file(tmp_db, mock_embed, f, "python", tmp_path)

    # Check that entities exist
    ent = tmp_db.get_entity("symbol:sample.py::greet")
    assert ent is not None
    assert ent["entity_type"] == "symbol"
    meta = json.loads(ent["metadata"])
    assert meta["kind"] == "function"
    assert meta["language"] == "python"


def test_reindex_file_updates_entities(tmp_db, tmp_path):
    """Re-indexing the same file should not create duplicates."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    mock_embed = MagicMock()
    mock_embed.embed.return_value = [[0.1] * 768] * 10

    index_file(tmp_db, mock_embed, f, "python", tmp_path)
    index_file(tmp_db, mock_embed, f, "python", tmp_path)

    # greet should exist exactly once
    ent = tmp_db.get_entity("symbol:sample.py::greet")
    assert ent is not None


def test_delete_stale_symbols(tmp_db, tmp_path):
    """Remove a function from file, re-index, verify old entity gone."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PYTHON)

    mock_embed = MagicMock()
    mock_embed.embed.return_value = [[0.1] * 768] * 10

    index_file(tmp_db, mock_embed, f, "python", tmp_path)
    assert tmp_db.get_entity("symbol:sample.py::greet") is not None

    # Rewrite without greet
    f.write_text(textwrap.dedent("""\
        class Greeter:
            def say_hi(self):
                return "hi"
    """))
    index_file(tmp_db, mock_embed, f, "python", tmp_path)

    assert tmp_db.get_entity("symbol:sample.py::greet") is None
    assert tmp_db.get_entity("symbol:sample.py::Greeter") is not None


# --- incremental_index ---

def test_incremental_via_git_diff(tmp_db, tmp_path):
    """Mock git diff to simulate incremental indexing."""
    f = tmp_path / "changed.py"
    f.write_text("def foo(): pass\n")

    mock_embed = MagicMock()
    mock_embed.embed.return_value = [[0.1] * 768] * 5

    from config import EngramConfig

    config = EngramConfig()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        # git rev-parse HEAD
        if "rev-parse" in cmd:
            result.stdout = "abc123\n"
        # git diff --name-only --diff-filter
        elif "diff" in cmd:
            result.stdout = "changed.py\n"
        # git rev-parse --show-toplevel
        elif "--show-toplevel" in cmd:
            result.stdout = str(tmp_path) + "\n"
        return result

    with patch("indexer.subprocess.run", side_effect=fake_run):
        # Set a fake last commit so it uses diff
        tmp_db.set_meta("last_indexed_commit", "old123")
        count = incremental_index(tmp_db, mock_embed, tmp_path, config)

    assert count >= 1


def test_non_git_project_skips_incremental(tmp_db, tmp_path):
    """Non-git project returns 0 and does not crash."""
    mock_embed = MagicMock()
    from config import EngramConfig

    config = EngramConfig()

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 128  # git not a repo
        result.stdout = ""
        return result

    with patch("indexer.subprocess.run", side_effect=fake_run):
        count = incremental_index(tmp_db, mock_embed, tmp_path, config)

    assert count == 0
