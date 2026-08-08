"""Streaming resource benchmark for the bounded category compiler."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Iterator, Sequence

from categories import EvolvingCategoryStore
from category_compile import CategoryCompiler, CompileBudget


BATCH_SIZE = 10_000
ACCEPTANCE_CELLS = 1_000_000
RSS_GATE_BYTES = 1 << 30
BENCHMARK_OUTPUT_SCHEMA = "engram.category-evolution.benchmark-output"
BENCHMARK_SCHEMA_VERSION = 1
EXPECTED_FRONTIER_CANDIDATES = 41
EXPECTED_FRONTIER_HOPS = 4


def _require_exact_object(
    value: object, expected: set[str], label: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _require_nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _validate_benchmark_report(
    value: object, expected_cells: int,
) -> dict[str, object]:
    """Validate the complete child output before it can influence acceptance."""
    if type(expected_cells) is not int or expected_cells <= 0:
        raise ValueError("expected cells must be a positive integer")
    core_fields = {
        "schema", "schema_version", "cells", "batch_size", "streaming",
        "rss_platform_semantics", "baseline_peak_rss_bytes", "peak_rss_bytes",
        "incremental_peak_rss_bytes", "snapshot_content_hash", "topology", "compiler",
    }
    public_fields = {"acceptance_gate", "acceptance_run"}
    if not isinstance(value, dict) or set(value) not in (core_fields, core_fields | public_fields):
        raise ValueError("benchmark output has missing or unknown fields")
    report = value
    if report["schema"] != BENCHMARK_OUTPUT_SCHEMA:
        raise ValueError("benchmark output schema is unsupported")
    if type(report["schema_version"]) is not int or report["schema_version"] != BENCHMARK_SCHEMA_VERSION:
        raise ValueError("benchmark output version is unsupported")
    if type(report["cells"]) is not int or report["cells"] != expected_cells:
        raise ValueError("benchmark output cell count does not match the request")
    if type(report["batch_size"]) is not int or report["batch_size"] != BATCH_SIZE:
        raise ValueError("benchmark output batch size is invalid")
    if report["streaming"] is not True:
        raise ValueError("benchmark output must attest streamed construction")
    if not isinstance(report["rss_platform_semantics"], str) or not report["rss_platform_semantics"]:
        raise ValueError("benchmark RSS semantics are invalid")
    baseline = _require_nonnegative_integer(report["baseline_peak_rss_bytes"], "baseline RSS")
    peak = _require_nonnegative_integer(report["peak_rss_bytes"], "peak RSS")
    incremental = _require_nonnegative_integer(
        report["incremental_peak_rss_bytes"], "incremental RSS",
    )
    if incremental != max(0, peak - baseline):
        raise ValueError("benchmark RSS arithmetic is inconsistent")
    snapshot_hash = report["snapshot_content_hash"]
    if (
        not isinstance(snapshot_hash, str)
        or len(snapshot_hash) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_hash)
    ):
        raise ValueError("benchmark snapshot hash is invalid")

    topology = _require_exact_object(report["topology"], {
        "valid", "object_cells", "edge_cells", "boundary_rows",
    }, "benchmark topology")
    if topology["valid"] is not True:
        raise ValueError("benchmark topology is not valid")
    object_cells = _require_nonnegative_integer(topology["object_cells"], "object cells")
    edge_cells = _require_nonnegative_integer(topology["edge_cells"], "edge cells")
    boundary_rows = _require_nonnegative_integer(topology["boundary_rows"], "boundary rows")
    expected_objects, expected_edges = _topology_counts(expected_cells)
    if (
        (object_cells, edge_cells) != (expected_objects, expected_edges)
        or object_cells + edge_cells != expected_cells
        or boundary_rows != edge_cells * 2
    ):
        raise ValueError("benchmark topology counts are inconsistent")

    compiler = _require_exact_object(report["compiler"], {
        "purpose", "ran", "candidate_count", "cell_count", "truncated",
        "rotation_required", "token_count", "elapsed_wall_time_ms", "max_hops",
        "max_neighbors_observed", "raw_max_neighbors", "neighbor_limit_hit",
    }, "benchmark compiler observation")
    if compiler["purpose"] != "resource_benchmark" or type(compiler["ran"]) is not bool:
        raise ValueError("benchmark compiler run attestation is invalid")
    for field in (
        "candidate_count", "cell_count", "token_count", "max_hops",
        "max_neighbors_observed", "raw_max_neighbors",
    ):
        _require_nonnegative_integer(compiler[field], f"compiler {field}")
    for field in ("truncated", "rotation_required", "neighbor_limit_hit"):
        if type(compiler[field]) is not bool:
            raise ValueError(f"compiler {field} must be boolean")
    elapsed = compiler["elapsed_wall_time_ms"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise ValueError("compiler elapsed wall time is invalid")
    if compiler["cell_count"] > compiler["candidate_count"] or compiler["candidate_count"] > expected_cells:
        raise ValueError("benchmark compiler counts are inconsistent")
    effective_neighbors = min(compiler["raw_max_neighbors"], CompileBudget().max_neighbors)
    if (
        compiler["max_neighbors_observed"] > effective_neighbors
        or compiler["neighbor_limit_hit"] is not (compiler["raw_max_neighbors"] > CompileBudget().max_neighbors)
    ):
        raise ValueError("benchmark neighbor observations are inconsistent")
    if public_fields.issubset(report):
        gate = _require_exact_object(report["acceptance_gate"], {
            "threshold_bytes", "observed_bytes", "evaluated", "passed", "reason",
        }, "benchmark acceptance gate")
        if (
            type(gate["threshold_bytes"]) is not int
            or gate["threshold_bytes"] != RSS_GATE_BYTES
            or type(gate["observed_bytes"]) is not int
            or gate["observed_bytes"] != incremental
            or type(gate["evaluated"]) is not bool
            or type(gate["passed"]) is not bool
            or (gate["reason"] is not None and not isinstance(gate["reason"], str))
            or type(report["acceptance_run"]) is not bool
        ):
            raise ValueError("benchmark acceptance metadata is invalid")
    return report


def run_benchmark(*, cells: int, work_dir: Path) -> dict[str, object]:
    """Measure a child process so peak RSS has a meaningful per-run baseline.

    The work directory is only a parent for an exact ``mkdtemp`` directory,
    which is removed after the child exits.  The generated cells are yielded in
    10,000-cell SQLite batches; no Python collection stores all cell drafts.
    """
    if type(cells) is not int or cells <= 0:
        raise ValueError("cells must be a positive integer")
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="category-resource-", dir=work_dir))
    try:
        environment = os.environ.copy()
        environment["TMPDIR"] = str(temporary)
        completed = subprocess.run(
            [
                sys.executable, "-c",
                ("import json; from experiments.category_evolution.benchmark import _worker; "
                 f"print(json.dumps(_worker({cells}), sort_keys=True, separators=(',', ':')))"),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "resource benchmark worker failed")
        report = json.loads(completed.stdout)
        _validate_benchmark_report(report, cells)
    finally:
        # This is the exact directory created above, never a user-provided path.
        shutil.rmtree(temporary)
    report["acceptance_gate"] = _benchmark_acceptance(cells, report)
    report["acceptance_run"] = cells == ACCEPTANCE_CELLS
    _validate_benchmark_report(report, cells)
    return report


def _benchmark_acceptance(cells: int, report: dict[str, object]) -> dict[str, object]:
    try:
        report = _validate_benchmark_report(report, cells)
    except ValueError as exc:
        observed = report.get("incremental_peak_rss_bytes") if isinstance(report, dict) else None
        return {
            "threshold_bytes": RSS_GATE_BYTES,
            "observed_bytes": observed if type(observed) is int else None,
            "evaluated": type(cells) is int and cells == ACCEPTANCE_CELLS,
            "passed": False,
            "reason": f"compiler frontier was incomplete or benchmark output was invalid: {exc}",
        }
    observed = report["incremental_peak_rss_bytes"]
    compiler = report["compiler"]
    assert type(observed) is int and isinstance(compiler, dict)
    frontier_complete = (
        compiler["candidate_count"] >= EXPECTED_FRONTIER_CANDIDATES
        and compiler["max_hops"] >= EXPECTED_FRONTIER_HOPS
    )
    evaluated = cells == ACCEPTANCE_CELLS
    compiler_within_caps = (
        compiler["max_hops"] <= 4
        and compiler["max_neighbors_observed"] <= 64
        and compiler["candidate_count"] <= 50_000
        and compiler["elapsed_wall_time_ms"] <= 500
        and compiler["token_count"] <= 65_536
    )
    passed = (
        evaluated
        and report["topology"]["valid"] is True
        and compiler["ran"] is True
        and observed < RSS_GATE_BYTES
        and frontier_complete
        and compiler_within_caps
    )
    if not evaluated:
        reason = "requires explicit --cells 1000000"
    elif report["topology"]["valid"] is not True:
        reason = "benchmark topology was invalid"
    elif compiler["ran"] is not True:
        reason = "compiler did not run"
    elif not frontier_complete:
        reason = "compiler frontier was incomplete"
    elif observed >= RSS_GATE_BYTES:
        reason = "incremental peak RSS did not satisfy the 1 GiB gate"
    elif not compiler_within_caps:
        reason = "compiler exceeded a production upper bound"
    else:
        reason = None
    return {
        "threshold_bytes": RSS_GATE_BYTES,
        "observed_bytes": observed,
        "evaluated": evaluated,
        "passed": passed,
        "reason": reason,
    }


def _worker(cells: int) -> dict[str, object]:
    """Own the worker database path so imported callers cannot select a target."""
    if type(cells) is not int or cells <= 0:
        raise ValueError("cells must be a positive integer")
    baseline = _rss_bytes()
    temporary = Path(tempfile.mkdtemp(prefix="category-resource-worker-"))
    database = temporary / "categories_v2.db"
    connection: sqlite3.Connection | None = None
    store: EvolvingCategoryStore | None = None
    compiler: CategoryCompiler | None = None
    try:
        connection = sqlite3.connect(database)
        store = EvolvingCategoryStore(connection)
        _insert_streamed_cells(store, cells)
        epoch_id = "benchmark-root"
        snapshot_content_hash = _write_epoch_snapshot(connection, epoch_id, cells)
        topology = _validate_topology(connection, cells)
        compiler = CategoryCompiler(store, CompileBudget())
        started = time.monotonic_ns()
        compiled = compiler.compile(epoch_id, seed_cell_ids=("object-0000000",))
        elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
        raw_max_neighbors, max_neighbors_observed, neighbor_limit_hit = (
            _compiled_neighbor_observations(connection, compiled.cells, compiler.budget)
        )
        peak = _rss_bytes()
        return {
            "schema": BENCHMARK_OUTPUT_SCHEMA,
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "cells": cells,
            "batch_size": BATCH_SIZE,
            "streaming": True,
            "rss_platform_semantics": _rss_semantics(),
            "baseline_peak_rss_bytes": baseline,
            "peak_rss_bytes": peak,
            "incremental_peak_rss_bytes": max(0, peak - baseline),
            "snapshot_content_hash": snapshot_content_hash,
            "topology": topology,
            "compiler": {
                "purpose": "resource_benchmark",
                "ran": True,
                "candidate_count": compiled.candidate_count,
                "cell_count": len(compiled.cells),
                "truncated": compiled.truncated,
                "rotation_required": compiled.rotation_required,
                "token_count": compiled.token_count,
                "elapsed_wall_time_ms": elapsed_ms,
                "max_hops": max((cell.hops for cell in compiled.cells), default=0),
                "max_neighbors_observed": max_neighbors_observed,
                "raw_max_neighbors": raw_max_neighbors,
                "neighbor_limit_hit": neighbor_limit_hit,
            },
        }
    finally:
        if compiler is not None:
            compiler.close()
        if store is not None:
            store.close()
        elif connection is not None:
            connection.close()
        shutil.rmtree(temporary)


def _insert_streamed_cells(store: EvolvingCategoryStore, cells: int) -> None:
    """Insert a valid object/edge category in batches of at most 10,000 rows."""
    object_cells, edge_cells = _topology_counts(cells)
    created_at = datetime.now(timezone.utc).isoformat()
    with store.transaction(immediate=True) as connection:
        for start in range(0, object_cells, BATCH_SIZE):
            end = min(start + BATCH_SIZE, object_cells)
            connection.executemany(
                """
                INSERT INTO cat_cells
                    (id, dimension, content, context_id, payload_json, content_hash,
                     created_event_id, created_at)
                VALUES (?, 0, ?, NULL, '{}', ?, NULL, ?)
                """,
                _object_rows(start, end, created_at),
            )
        for start in range(0, edge_cells, BATCH_SIZE):
            end = min(start + BATCH_SIZE, edge_cells)
            connection.executemany(
                """
                INSERT INTO cat_cells
                    (id, dimension, content, context_id, payload_json, content_hash,
                     created_event_id, created_at)
                VALUES (?, 1, ?, NULL, '{}', ?, NULL, ?)
                """,
                _edge_rows(start, end, created_at),
            )
        # Each edge has two boundary rows.  A 5,000-edge chunk therefore keeps
        # every executemany call at or below the public 10,000-row batch bound.
        for start in range(0, edge_cells, BATCH_SIZE // 2):
            end = min(start + BATCH_SIZE // 2, edge_cells)
            connection.executemany(
                """
                INSERT INTO cat_boundaries (cell_id, side, position, boundary_id)
                VALUES (?, ?, 0, ?)
                """,
                _boundary_rows(start, end),
            )


def _topology_counts(cells: int) -> tuple[int, int]:
    edge_cells = (cells - 1) // 2
    return cells - edge_cells, edge_cells


def _object_rows(start: int, end: int, created_at: str) -> Iterator[tuple[str, str, str, str]]:
    for number in range(start, end):
        identifier = f"object-{number:07d}"
        content = f"benchmark object {number}"
        yield identifier, content, hashlib.sha256(content.encode()).hexdigest(), created_at


def _edge_rows(start: int, end: int, created_at: str) -> Iterator[tuple[str, str, str, str]]:
    for number in range(start, end):
        identifier = f"edge-{number:07d}"
        content = f"benchmark edge {number}"
        yield identifier, content, hashlib.sha256(content.encode()).hexdigest(), created_at


def _boundary_rows(start: int, end: int) -> Iterator[tuple[str, str, str]]:
    for number in range(start, end):
        edge_id = f"edge-{number:07d}"
        yield edge_id, "source", f"object-{number // 4:07d}"
        yield edge_id, "target", f"object-{number + 1:07d}"


def _write_epoch_snapshot(connection: sqlite3.Connection, epoch_id: str, cells: int) -> str:
    """Materialize membership inside SQLite; Python never holds cell IDs or JSON."""
    event_id = "benchmark-epoch-event"
    created_at = datetime.now(timezone.utc).isoformat()
    snapshot_content_hash = _streamed_snapshot_hash(connection)
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
        (event_id, "benchmark_epoch", "{}", created_at),
    )
    connection.execute(
        "INSERT INTO cat_epochs (id, created_event_id, created_at) VALUES (?, ?, ?)",
        (epoch_id, event_id, created_at),
    )
    connection.execute(
        """INSERT INTO cat_snapshots (id, epoch_id, active_cell_ids_json, content_hash, created_at)
           SELECT ?, ?, json_group_array(id), ?, ?
           FROM (SELECT id FROM cat_cells ORDER BY id)""",
        ("benchmark-snapshot", epoch_id, snapshot_content_hash, created_at),
    )
    connection.commit()
    return snapshot_content_hash


def _validate_topology(connection: sqlite3.Connection, cells: int) -> dict[str, object]:
    """Prove the streamed fixture satisfies the production dimension invariant."""
    expected_objects, expected_edges = _topology_counts(cells)
    object_cells = int(connection.execute(
        "SELECT COUNT(*) FROM cat_cells WHERE dimension = 0"
    ).fetchone()[0])
    edge_cells = int(connection.execute(
        "SELECT COUNT(*) FROM cat_cells WHERE dimension = 1"
    ).fetchone()[0])
    boundary_rows = int(connection.execute("SELECT COUNT(*) FROM cat_boundaries").fetchone()[0])
    invalid_edges = int(connection.execute(
        """
        SELECT COUNT(*) FROM cat_cells AS edge
        WHERE edge.dimension = 1 AND (
            (SELECT COUNT(*) FROM cat_boundaries AS boundary
             WHERE boundary.cell_id = edge.id AND boundary.side = 'source'
                   AND boundary.position = 0) != 1
            OR (SELECT COUNT(*) FROM cat_boundaries AS boundary
                WHERE boundary.cell_id = edge.id AND boundary.side = 'target'
                      AND boundary.position = 0) != 1
            OR (SELECT COUNT(*) FROM cat_boundaries AS boundary
                WHERE boundary.cell_id = edge.id) != 2
            OR EXISTS (
                SELECT 1 FROM cat_boundaries AS boundary
                JOIN cat_cells AS endpoint ON endpoint.id = boundary.boundary_id
                WHERE boundary.cell_id = edge.id AND endpoint.dimension != 0
            )
        )
        """
    ).fetchone()[0])
    invalid_zero_cells = int(connection.execute(
        """
        SELECT COUNT(*) FROM cat_boundaries AS boundary
        JOIN cat_cells AS cell ON cell.id = boundary.cell_id
        WHERE cell.dimension = 0
        """
    ).fetchone()[0])
    invalid_dimensions = int(connection.execute(
        "SELECT COUNT(*) FROM cat_cells WHERE dimension NOT IN (0, 1)"
    ).fetchone()[0])
    valid = (
        object_cells == expected_objects
        and edge_cells == expected_edges
        and object_cells + edge_cells == cells
        and boundary_rows == edge_cells * 2
        and invalid_edges == 0
        and invalid_zero_cells == 0
        and invalid_dimensions == 0
    )
    if not valid:
        raise RuntimeError("streamed benchmark topology violated category invariants")
    return {
        "valid": True,
        "object_cells": object_cells,
        "edge_cells": edge_cells,
        "boundary_rows": boundary_rows,
    }


def _compiled_neighbor_observations(
    connection: sqlite3.Connection,
    cells: Sequence[object],
    budget: CompileBudget,
) -> tuple[int, int, bool]:
    """Measure raw and admitted neighbors only for actual expanded cells."""
    connection.execute(
        "CREATE TEMP TABLE benchmark_compiled (id TEXT PRIMARY KEY, hops INTEGER NOT NULL)"
    )
    try:
        connection.executemany(
            "INSERT INTO benchmark_compiled (id, hops) VALUES (?, ?)",
            ((str(cell.id), int(cell.hops)) for cell in cells),
        )
        adjacency_sql = """
            SELECT cell_id AS node_id, boundary_id AS neighbor_id FROM cat_boundaries
            UNION ALL
            SELECT boundary_id AS node_id, cell_id AS neighbor_id FROM cat_boundaries
        """
        raw_max_neighbors = int(connection.execute(f"""
            WITH adjacency AS ({adjacency_sql})
            SELECT COALESCE(MAX(neighbor_count), 0)
            FROM (
                SELECT expanded.id, COUNT(DISTINCT adjacency.neighbor_id) AS neighbor_count
                FROM benchmark_compiled AS expanded
                LEFT JOIN adjacency ON adjacency.node_id = expanded.id
                WHERE expanded.hops < ?
                GROUP BY expanded.id
            )
        """, (budget.max_depth,)).fetchone()[0])
        max_neighbors_observed = int(connection.execute(f"""
            WITH adjacency AS ({adjacency_sql})
            SELECT COALESCE(MAX(neighbor_count), 0)
            FROM (
                SELECT expanded.id, COUNT(DISTINCT admitted.id) AS neighbor_count
                FROM benchmark_compiled AS expanded
                LEFT JOIN adjacency ON adjacency.node_id = expanded.id
                LEFT JOIN benchmark_compiled AS admitted
                    ON admitted.id = adjacency.neighbor_id
                WHERE expanded.hops < ?
                GROUP BY expanded.id
            )
        """, (budget.max_depth,)).fetchone()[0])
        return (
            raw_max_neighbors,
            max_neighbors_observed,
            raw_max_neighbors > budget.max_neighbors,
        )
    finally:
        connection.execute("DROP TABLE benchmark_compiled")


def _streamed_snapshot_hash(connection: sqlite3.Connection) -> str:
    """Hash canonical membership incrementally without a Python list or join."""
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for row in connection.execute("SELECT id FROM cat_cells ORDER BY id"):
        if not first:
            digest.update(b",")
        digest.update(json.dumps(str(row[0]), separators=(",", ":")).encode())
        first = False
    digest.update(b"]")
    return digest.hexdigest()


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _rss_semantics() -> str:
    unit = "bytes" if sys.platform == "darwin" else "KiB"
    return f"resource.getrusage(RUSAGE_SELF).ru_maxrss lifetime peak in {unit}; child baseline subtracted"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=int, required=True)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.work_dir is None:
            raise ValueError("--work-dir is required")
        report = run_benchmark(cells=args.cells, work_dir=args.work_dir)
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
