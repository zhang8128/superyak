"""Behavioral tests for deterministic, read-only legacy category replay."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

def _legacy_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cells (
            id TEXT PRIMARY KEY,
            level INTEGER NOT NULL,
            source_id TEXT,
            target_id TEXT,
            content TEXT NOT NULL,
            context TEXT,
            created_at TEXT NOT NULL,
            accessed_at TEXT,
            access_count INTEGER
        );
        """
    )
    return connection


def _insert_legacy_cell(
    connection: sqlite3.Connection,
    cell_id: str,
    level: int,
    source_id: str | None,
    target_id: str | None,
    content: str,
) -> None:
    connection.execute(
        """
        INSERT INTO cells
            (id, level, source_id, target_id, content, context, created_at, access_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cell_id, level, source_id, target_id, content, '{"origin":"legacy"}', "2026-08-07T00:00:00+00:00", 0),
    )


def _make_legacy_history(path: Path) -> None:
    connection = _legacy_connection(path)
    _insert_legacy_cell(connection, "arrow-alpha", 1, "memory-alpha", "memory-beta", "alpha to beta")
    _insert_legacy_cell(connection, "arrow-beta", 1, "memory-beta", "memory-alpha", "beta to alpha")
    _insert_legacy_cell(connection, "transfer", 2, "arrow-alpha", "arrow-beta", "transfer")
    connection.commit()
    connection.close()


def _importer():
    return importlib.import_module("category_evolution")


def _v2_cell_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM cat_cells").fetchone()[0]
    finally:
        connection.close()


def test_legacy_importer_module_is_available():
    """Catches removal of the replay entry point required by operators."""
    _importer()


def test_legacy_replay_creates_deterministic_proxies_cells_and_snapshot(tmp_path):
    """Catches replay that changes identity or omits a valid legacy relationship."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    evolution = _importer()
    first = evolution.import_legacy_category(legacy, tmp_path / "first-v2.db")
    second = evolution.import_legacy_category(legacy, tmp_path / "second-v2.db")

    for report in (first, second):
        assert report.legacy_total == 3
        assert report.proxy_zero_cells == 2
        assert report.imported_one_cells == 2
        assert report.imported_two_cells == 1
        assert report.opaque_cells == 0
        assert report.unexplained_loss == 0
        assert _v2_cell_count(tmp_path / ("first-v2.db" if report is first else "second-v2.db")) == 5
    assert first.snapshot_hash == second.snapshot_hash
    assert first.root_epoch_id == second.root_epoch_id
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns

    replayed = evolution.import_legacy_category(legacy, tmp_path / "first-v2.db")
    assert replayed == first
    assert _v2_cell_count(tmp_path / "first-v2.db") == 5


def test_legacy_replay_has_one_snapshot_hash_across_three_independent_outputs(tmp_path):
    """Catches dependence on output database identity, insertion order, or wall-clock time."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)

    evolution = _importer()
    reports = [
        evolution.import_legacy_category(legacy, tmp_path / f"v2-{index}.db")
        for index in range(3)
    ]

    assert {report.snapshot_hash for report in reports} == {reports[0].snapshot_hash}
    assert {report.root_epoch_id for report in reports} == {reports[0].root_epoch_id}
    assert all(_v2_cell_count(tmp_path / f"v2-{index}.db") == 5 for index in range(3))


def test_legacy_replay_counts_missing_level_two_reference_as_loss_without_proxy(tmp_path):
    """Catches a malformed transfer being repaired with an invented category target."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "arrow", 1, "memory-alpha", "memory-beta", "valid arrow")
    _insert_legacy_cell(connection, "broken-transfer", 2, "arrow", "missing-arrow", "broken")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.legacy_total == 2
    assert report.imported_one_cells == 1
    assert report.imported_two_cells == 0
    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 3
    connection = sqlite3.connect(tmp_path / "v2.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM cat_cells WHERE id = 'missing-arrow'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_replay_cli_is_read_only_reports_json_and_returns_two_for_loss(tmp_path):
    """Catches the CLI opening its source database writable or hiding partial replay loss."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "broken", 2, "missing-a", "missing-b", "broken")
    connection.commit()
    connection.close()
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns
    output = tmp_path / "v2.db"
    script = Path(__file__).parents[1] / "category_evolution.py"

    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(legacy), "--output", str(output), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["unexplained_loss"] == 1
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_replay_cli_refuses_the_same_resolved_legacy_and_output_path(tmp_path):
    """Catches a destructive invocation that points v2 output at the legacy source."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns
    script = Path(__file__).parents[1] / "category_evolution.py"

    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(legacy), "--output", str(legacy), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 2
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_legacy_replay_refuses_a_hard_link_to_the_legacy_database(tmp_path):
    """Catches an alias that would make the v2 output write into legacy storage."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    hard_link = tmp_path / "categories-hard-link.db"
    os.link(legacy, hard_link)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    with pytest.raises(ValueError, match="different paths"):
        _importer().import_legacy_category(legacy, hard_link)

    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns
