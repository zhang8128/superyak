"""Streaming resource benchmark for the bounded category compiler."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
    database = temporary / "categories_v2.db"
    try:
        completed = subprocess.run(
            [
                sys.executable, "-c",
                ("import json; from pathlib import Path; "
                 "from experiments.category_evolution.benchmark import _worker; "
                 f"print(json.dumps(_worker({cells}, Path({str(database)!r})), sort_keys=True, separators=(',', ':')))"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "resource benchmark worker failed")
        report = json.loads(completed.stdout)
        if not isinstance(report, dict):
            raise RuntimeError("resource benchmark worker emitted malformed JSON")
    finally:
        # This is the exact directory created above, never a user-provided path.
        shutil.rmtree(temporary)
    observed = int(report["incremental_peak_rss_bytes"])
    evaluated = cells == ACCEPTANCE_CELLS
    report["acceptance_gate"] = {
        "threshold_bytes": RSS_GATE_BYTES,
        "observed_bytes": observed,
        "evaluated": evaluated,
        "passed": evaluated and observed < RSS_GATE_BYTES,
        "reason": None if evaluated else "requires explicit --cells 1000000",
    }
    report["acceptance_run"] = evaluated
    return report


def _worker(cells: int, database: Path) -> dict[str, object]:
    baseline = _rss_bytes()
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    compiler: CategoryCompiler | None = None
    try:
        _insert_streamed_cells(store, cells)
        epoch_id = "benchmark-root"
        _write_epoch_snapshot(connection, epoch_id, cells)
        compiler = CategoryCompiler(store, CompileBudget())
        started = time.monotonic_ns()
        compiled = compiler.compile(epoch_id, seed_cell_ids=("cell-0000000",))
        elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
        peak = _rss_bytes()
        return {
            "schema_version": 1,
            "cells": cells,
            "batch_size": BATCH_SIZE,
            "streaming": True,
            "rss_platform_semantics": _rss_semantics(),
            "baseline_peak_rss_bytes": baseline,
            "peak_rss_bytes": peak,
            "incremental_peak_rss_bytes": max(0, peak - baseline),
            "compiler": {
                "ran": True,
                "candidate_count": compiled.candidate_count,
                "cell_count": len(compiled.cells),
                "truncated": compiled.truncated,
                "token_count": compiled.token_count,
                "elapsed_wall_time_ms": elapsed_ms,
            },
        }
    finally:
        if compiler is not None:
            compiler.close()
        store.close()


def _insert_streamed_cells(store: EvolvingCategoryStore, cells: int) -> None:
    """Insert bounded batches directly through the store-owned schema transaction."""
    created_at = datetime.now(timezone.utc).isoformat()
    with store.transaction(immediate=True) as connection:
        for start in range(0, cells, BATCH_SIZE):
            end = min(start + BATCH_SIZE, cells)
            connection.executemany(
                """
                INSERT INTO cat_cells
                    (id, dimension, content, context_id, payload_json, content_hash,
                     created_event_id, created_at)
                VALUES (?, 0, ?, NULL, '{}', ?, NULL, ?)
                """,
                _cell_rows(start, end, created_at),
            )


def _cell_rows(start: int, end: int, created_at: str) -> Iterator[tuple[str, str, str, str]]:
    for number in range(start, end):
        identifier = f"cell-{number:07d}"
        content = f"benchmark cell {number}"
        yield identifier, content, hashlib.sha256(content.encode()).hexdigest(), created_at


def _write_epoch_snapshot(connection: sqlite3.Connection, epoch_id: str, cells: int) -> None:
    """Materialize membership inside SQLite; Python never holds cell IDs or JSON."""
    event_id = "benchmark-epoch-event"
    created_at = datetime.now(timezone.utc).isoformat()
    # A bounded 4-ary frontier stays meaningful in the 1K shape run (341
    # reachable cells at depth 4) without turning its MMR pass into a timeout.
    frontier = min(cells, 50_000)
    connection.executemany(
        "INSERT INTO cat_boundaries (cell_id, side, position, boundary_id) VALUES (?, 'source', ?, ?)",
        ((f"cell-{((number - 1) // 4):07d}", (number - 1) % 4, f"cell-{number:07d}")
         for number in range(1, frontier)),
    )
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
        ("benchmark-snapshot", epoch_id, "benchmark-sql-materialized", created_at),
    )
    connection.commit()


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
