"""Behavioral tests for deterministic, read-only legacy category replay."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest

from categories import CellDraft, EvolvingCategoryStore

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
    context: str = '{"origin":"legacy"}',
) -> None:
    connection.execute(
        """
        INSERT INTO cells
            (id, level, source_id, target_id, content, context, created_at, access_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cell_id, level, source_id, target_id, content, context, "2026-08-07T00:00:00+00:00", 0),
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


def _v2_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("cat_events", "cat_cells", "cat_epochs", "cat_snapshots")
        }
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
    assert _v2_counts(tmp_path / "first-v2.db") == {
        "cat_events": 1,
        "cat_cells": 5,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


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

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: legacy input and v2 output")
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


def test_legacy_replay_is_atomic_when_an_existing_cell_conflicts(tmp_path):
    """Catches bootstrap rows committing before a later v2 cell conflict aborts."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    connection = sqlite3.connect(output)
    store = EvolvingCategoryStore(connection)
    store.create_cell(CellDraft("arrow-alpha", 0, "conflicting existing cell"))
    store.close()

    with pytest.raises(ValueError, match="conflicting"):
        _importer().import_legacy_category(legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 0,
        "cat_cells": 1,
        "cat_epochs": 0,
        "cat_snapshots": 0,
    }


def test_legacy_replay_rejects_incompatible_output_before_schema_bootstrap(tmp_path):
    """Catches compatibility validation mutating an output it is about to reject."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "incompatible.db"
    _make_legacy_history(legacy)
    connection = sqlite3.connect(output)
    connection.execute("CREATE TABLE cat_events (id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO cat_events VALUES ('unrelated')")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)

    connection = sqlite3.connect(output)
    try:
        assert {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        } == {"cat_events"}
        assert connection.execute("SELECT id FROM cat_events").fetchone()[0] == "unrelated"
    finally:
        connection.close()


def test_legacy_replay_rejects_stale_output_with_same_active_ids(tmp_path):
    """Catches id-only snapshot matching that silently accepts changed source content."""
    first_legacy = tmp_path / "first.db"
    changed_legacy = tmp_path / "changed.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(first_legacy)
    connection = _legacy_connection(changed_legacy)
    _insert_legacy_cell(connection, "arrow-alpha", 1, "memory-alpha", "memory-beta", "changed alpha")
    _insert_legacy_cell(connection, "arrow-beta", 1, "memory-beta", "memory-alpha", "beta to alpha")
    _insert_legacy_cell(connection, "transfer", 2, "arrow-alpha", "arrow-beta", "transfer")
    connection.commit()
    connection.close()

    _importer().import_legacy_category(first_legacy, output)
    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(changed_legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 1,
        "cat_cells": 5,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


def test_legacy_replay_rejects_a_completed_output_with_unrelated_rows(tmp_path):
    """Catches idempotence blessing a completed replay contaminated by extra rows."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
        ("unrelated-event", "unrelated", "{}", "now"),
    )
    connection.execute(
        """
        INSERT INTO cat_cells
            (id, dimension, content, payload_json, content_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "unrelated-cell",
            0,
            "unrelated",
            "{}",
            hashlib.sha256(b"unrelated").hexdigest(),
            "now",
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 2,
        "cat_cells": 6,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


def test_legacy_replay_rejects_an_unsupported_output_schema_version(tmp_path):
    """Catches preflight accepting a completed replay with unsupported schema history."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute(
        "INSERT INTO cat_schema_version (version, applied_at) VALUES (2, 'now')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_rejects_contaminated_or_invalid_vector_state(tmp_path):
    """Catches optional vector storage bypassing exact replay preflight checks."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("DROP TABLE IF EXISTS cat_vectors")
    connection.execute("CREATE TABLE cat_vectors (cell_id TEXT)")
    connection.execute("INSERT INTO cat_vectors VALUES ('unrelated')")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_accepts_an_empty_valid_vec0_table(tmp_path):
    """Catches preflight rejecting sqlite-vec's legitimate empty shadow-table layout."""
    import sqlite_vec

    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    first = _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    connection.execute(
        "CREATE VIRTUAL TABLE cat_vectors USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768])"
    )
    connection.commit()
    connection.close()

    assert _importer().import_legacy_category(legacy, output) == first


def test_legacy_replay_rejects_a_completed_output_with_changed_context_id(tmp_path):
    """Catches exact replay validation overlooking a persisted cell context reference."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("DROP TRIGGER cat_cells_no_update")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "UPDATE cat_cells SET context_id = 'unrecorded-context' WHERE id = 'arrow-alpha'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible|does not match source"):
        _importer().import_legacy_category(legacy, output)


def test_level_two_requires_two_imported_level_one_boundaries(tmp_path):
    """Catches transfers accepting zero-cells or other transfers as boundaries."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "zero", 0, None, None, "legacy zero")
    _insert_legacy_cell(connection, "arrow-a", 1, "memory-a", "memory-b", "a")
    _insert_legacy_cell(connection, "arrow-b", 1, "memory-b", "memory-a", "b")
    _insert_legacy_cell(connection, "transfer-a", 2, "arrow-a", "arrow-b", "valid transfer")
    _insert_legacy_cell(connection, "transfer-b", 2, "arrow-a", "zero", "zero boundary")
    _insert_legacy_cell(connection, "transfer-c", 2, "transfer-a", "arrow-b", "two boundary")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.imported_two_cells == 1
    assert report.unexplained_loss == 2
    connection = sqlite3.connect(tmp_path / "v2.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM cat_cells WHERE id IN ('transfer-b', 'transfer-c')"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_legacy_replay_preserves_full_cell_structure_and_bootstrap_linkage(tmp_path):
    """Catches persistence that changes proxy IDs, cell structure, or bootstrap linkage."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "arrow-a", 1, "memory-a", "memory-b", "a", '{"tag":"a"}')
    _insert_legacy_cell(connection, "arrow-b", 1, "memory-b", "memory-a", "b", '{"tag":"b"}')
    _insert_legacy_cell(connection, "transfer", 2, "arrow-a", "arrow-b", "transfer")
    _insert_legacy_cell(connection, "opaque", 3, "missing-a", "missing-b", "opaque")
    connection.commit()
    connection.close()
    output = tmp_path / "v2.db"

    report = _importer().import_legacy_category(legacy, output)
    expected_a = str(uuid.uuid5(uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223"), "memory:memory-a"))
    expected_b = str(uuid.uuid5(uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223"), "memory:memory-b"))
    connection = sqlite3.connect(output)
    try:
        cells = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT id, dimension, content, payload_json FROM cat_cells ORDER BY id"
            )
        }
        assert set(cells) == {expected_a, expected_b, "arrow-a", "arrow-b", "transfer", "opaque"}
        assert cells["arrow-a"][:2] == (1, "a")
        assert json.loads(cells["arrow-a"][2])["legacy"]["context"] == '{"tag":"a"}'
        assert cells["transfer"][:2] == (2, "transfer")
        assert cells["opaque"][:2] == (3, "opaque")
        assert json.loads(cells["opaque"][2])["legacy"]["source_id"] == "missing-a"
        boundaries = connection.execute(
            "SELECT cell_id, side, position, boundary_id FROM cat_boundaries ORDER BY cell_id, side, position"
        ).fetchall()
        assert boundaries == [
            ("arrow-a", "source", 0, expected_a),
            ("arrow-a", "target", 0, expected_b),
            ("arrow-b", "source", 0, expected_b),
            ("arrow-b", "target", 0, expected_a),
            ("transfer", "source", 0, "arrow-a"),
            ("transfer", "target", 0, "arrow-b"),
        ]
        event_id, kind, payload_json = connection.execute(
            "SELECT id, kind, payload_json FROM cat_events"
        ).fetchone()
        assert kind == "legacy_import_summary"
        assert "manifest_fingerprint" in json.loads(payload_json)
        epoch = connection.execute(
            "SELECT id, rewrite_id, created_event_id FROM cat_epochs"
        ).fetchone()
        assert epoch == (report.root_epoch_id, None, event_id)
        snapshot = connection.execute(
            "SELECT epoch_id, active_cell_ids_json, content_hash FROM cat_snapshots"
        ).fetchone()
        assert snapshot[0] == report.root_epoch_id
        assert snapshot[1] == json.dumps(sorted(cells), separators=(",", ":"))
        assert snapshot[2] == report.snapshot_hash
    finally:
        connection.close()


def test_legacy_replay_counts_malformed_level_one_as_loss(tmp_path):
    """Catches malformed level-one rows creating partial proxy relationships."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "broken-arrow", 1, "memory-a", None, "broken")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.proxy_zero_cells == 0
    assert report.imported_one_cells == 0
    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 0


def test_legacy_replay_counts_nonserializable_metadata_as_loss(tmp_path):
    """Catches malformed legacy metadata escaping validation into manifest encoding."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(
        connection,
        "blob-arrow",
        1,
        "memory-a",
        "memory-b",
        "blob metadata",
        sqlite3.Binary(b"not-json"),
    )
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 0


def test_legacy_replay_refuses_symlink_and_relative_aliases(tmp_path, monkeypatch):
    """Catches path aliases bypassing the legacy-source write protection."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    alias = tmp_path / "legacy-link.db"
    alias.symlink_to(legacy.name)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="different paths"):
        _importer().import_legacy_category(Path("categories.db"), Path("legacy-link.db"))


def test_replay_cli_reports_database_errors_on_stderr_without_traceback(tmp_path):
    """Catches CLI database errors leaking tracebacks or machine output to stdout."""
    script = Path(__file__).parents[1] / "category_evolution.py"
    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(tmp_path / "missing.db"), "--output", str(tmp_path / "v2.db"), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("arguments", [[], ["replay", "--legacy", "missing.db"]])
def test_replay_cli_reserves_exit_two_for_unexplained_loss(arguments):
    """Catches argument errors using the partial-replay loss exit status."""
    script = Path(__file__).parents[1] / "category_evolution.py"
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert "usage:" not in result.stderr
