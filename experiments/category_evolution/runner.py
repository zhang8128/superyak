"""Run one disposable evolving-category evaluation and emit a schema-stable JSON report."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Sequence

from categories import CategoryStore, CellDraft, EvolvingCategoryStore, WeightVector
from category_compile import CategoryCompiler, CompileBudget
from category_context import ContextTracker
from category_evolution import import_legacy_category, legacy_proxy_id

from .fixtures import FixtureCohort, fixture_cohort, fixture_hash
from .metrics import (
    boundary_metrics,
    direct_recall_regression,
    false_transfer_rate,
    mean_reciprocal_rank,
    relative_mrr_improvement,
)
from .benchmark import run_benchmark


DEFAULT_SEED = 20260807
GATE_THRESHOLDS = {
    "boundary_overall_f1": 0.80,
    "cross_context_relative_mrr_improvement": 0.15,
    "direct_recall_regression": 0.05,
    "false_transfer_rate": 0.10,
    "identical_replay_hashes": 3,
    "unexplained_replay_loss": 0,
    "compiler_conformance_wall_time_ms": 500,
    "incremental_peak_rss_bytes": 1 << 30,
}
_TUNING_FLAGS = ("soft_threshold", "hard_threshold", "hard_confirmations")


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, help="legacy categories.db opened read-only")
    parser.add_argument("--work-dir", required=True, type=Path, help="disposable v2 output directory")
    parser.add_argument("--cohort", choices=("development", "holdout"), required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--soft-threshold", type=float, default=None,
                        help="development-only ContextTracker soft boundary threshold")
    parser.add_argument("--hard-threshold", type=float, default=None,
                        help="development-only ContextTracker hard boundary threshold")
    parser.add_argument("--hard-confirmations", type=int, default=None,
                        help="development-only ContextTracker confirmation count")
    parser.add_argument("--resource-report", type=Path, help="informational only; never accepted for gates")
    parser.add_argument("--benchmark-cells", type=int, help="run the benchmark now; only 1000000 is acceptance evidence")
    return parser


def run_evaluation(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    cohort = fixture_cohort(args.cohort, seed=args.seed)
    legacy = _find_legacy(args.legacy)
    configuration = _configuration(args)
    boundary = _evaluate_boundaries(cohort, configuration)
    ranking = _evaluate_rankings(cohort, args.work_dir)
    report: dict[str, object] = {
        "schema_version": 1,
        "cohort": cohort.name,
        "seed": cohort.seed,
        "fixture_hash": fixture_hash(cohort),
        "fixture_cases": len(cohort.cases),
        "configuration": configuration,
        "boundary_metrics": boundary,
        "ranking": ranking,
        "compiler_limits": asdict(CompileBudget()),
        "import_report": None,
        "replay_hashes": [],
        "replay_identical": False,
        "compiler_probe": None,
        "compiler_probes": [],
        "environmental_limitation": None,
        "resource_benchmark": _run_requested_benchmark(args),
        "ranking_provenance": "controlled disposable fixture archive; not the supplied legacy archive",
        "replay_provenance": "supplied/discovered legacy archive is replayed independently",
    }
    if legacy is None:
        report["environmental_limitation"] = (
            "legacy categories.db was not found; replay and compiler measurements were not run"
        )
        report["acceptance"] = _acceptance(report)
        return report

    replay_hashes, import_reports, compiler_probe = _replay_three_times(legacy, args.work_dir)
    report["import_report"] = import_reports[0]
    report["import_reports"] = import_reports
    report["replay_hashes"] = replay_hashes
    report["replay_digests"] = replay_hashes
    report["replay_identical"] = len(replay_hashes) == 3 and len(set(replay_hashes)) == 1
    report["compiler_probe"] = compiler_probe
    report["compiler_probes"] = [compiler_probe, *ranking["compile_probes"]]
    report["acceptance"] = _acceptance(report)
    return report


def _validate_args(args: argparse.Namespace) -> None:
    if type(args.seed) is not int:
        raise ValueError("seed must be an integer")
    if args.cohort == "holdout" and any(getattr(args, flag) is not None for flag in _TUNING_FLAGS):
        raise ValueError("holdout rejects tuning overrides")
    if args.legacy is not None and args.legacy.exists() and not args.legacy.is_file():
        raise ValueError("legacy path must name a database file")
    if args.work_dir.exists() and not args.work_dir.is_dir():
        raise ValueError("work-dir must be a directory")
    if args.resource_report is not None:
        raise ValueError("resource-report is informational only; run --benchmark-cells 1000000 instead")
    if args.benchmark_cells is not None and args.benchmark_cells != 1_000_000:
        raise ValueError("benchmark-cells must be exactly 1000000")


def _run_requested_benchmark(args: argparse.Namespace) -> dict[str, object] | None:
    if args.benchmark_cells is None:
        return None
    return run_benchmark(cells=args.benchmark_cells, work_dir=args.work_dir)


def _find_legacy(explicit: Path | None) -> Path | None:
    if explicit is not None:
        if explicit.exists():
            return explicit.resolve()
        return None
    for root in (Path.cwd(), Path.cwd().parent, Path.cwd().parent.parent):
        candidate = root / ".engram" / "categories.db"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _configuration(args: argparse.Namespace) -> dict[str, object]:
    values: dict[str, object] = {
        "shadow": True,
        "influence_recall": False,
        "auto_commit": False,
        "soft_threshold": 0.35,
        "hard_threshold": 0.65,
        "hard_confirmations": 2,
        "tuning_mode": "development" if args.cohort == "development" else "frozen_holdout",
    }
    if args.cohort == "development":
        for flag in _TUNING_FLAGS:
            value = getattr(args, flag)
            if value is not None:
                values[flag] = value
    return values


def _evaluate_boundaries(cohort: FixtureCohort, configuration: dict[str, object]) -> dict[str, dict[str, float | int]]:
    rows: list[tuple[str, bool, bool]] = []
    for case in cohort.cases:
        tracker = ContextTracker(
            soft_threshold=float(configuration["soft_threshold"]),
            hard_threshold=float(configuration["hard_threshold"]),
            hard_confirmations=int(configuration["hard_confirmations"]),
        )
        if len(case.observations) != len(case.expected_decisions):
            raise ValueError("fixture observation/decision lengths differ")
        for observation, expected in zip(case.observations, case.expected_decisions, strict=True):
            decision = tracker.observe(observation)
            rows.append((case.kind, expected, decision.kind == "hard"))
    return boundary_metrics(rows)


def _evaluate_rankings(cohort: FixtureCohort, work_dir: Path) -> dict[str, object]:
    """Execute current-store lexical retrieval and shadow compiler ranking on one fixture archive.

    Fixture rows supply only relevance truth (which created record is relevant)
    and queries. Rankings, direct hits, and false transfers are observed from
    the two actual stores, not embedded in fixture expectations.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="category-ranking-", dir=work_dir))
    try:
        legacy = temporary / "current_categories.db"
        shadow = temporary / "shadow_categories_v2.db"
        baseline_rows, truths = _build_current_fixture_archive(legacy, cohort)
        imported = import_legacy_category(legacy, shadow)
        shadow_rankings, shadow_direct_rankings, compile_probes, cross_context_candidates = _compile_shadow_rankings(
            shadow, imported.root_epoch_id, truths, baseline_rows,
        )
        baseline_rankings = [(rows["query"], {truth["relevant_id"]}) for rows, truth in zip(baseline_rows, truths, strict=True)]
        baseline_direct_rankings = [(rows["direct"], {truth["relevant_id"]}) for rows, truth in zip(baseline_rows, truths, strict=True)]
        baseline_mrr = mean_reciprocal_rank(baseline_rankings)
        shadow_mrr = mean_reciprocal_rank(shadow_rankings)
        baseline_hits = sum(bool(ranking and ranking[0] in relevant) for ranking, relevant in baseline_direct_rankings)
        shadow_hits = sum(bool(ranking and ranking[0] in relevant) for ranking, relevant in shadow_direct_rankings)
        false_transfers = _false_cross_context_transfers(shadow_rankings, truths)
        return {
            "source": "category_compiler_fixture_db",
            "baseline_mrr": baseline_mrr,
            "shadow_mrr": shadow_mrr,
            "relative_mrr_improvement": relative_mrr_improvement(baseline_mrr, shadow_mrr),
            "direct_recall_baseline_hits": baseline_hits,
            "direct_recall_shadow_hits": shadow_hits,
            "direct_recall_regression": direct_recall_regression(baseline_hits, shadow_hits),
            "direct_recall_evaluated": baseline_hits > 0,
            "false_transfer_rate": None if not false_transfers else false_transfer_rate(false_transfers),
            "false_transfer_evaluated": bool(false_transfers),
            "fixture_import": asdict(imported),
            "direct_seed_source": "baseline_direct_top",
            "cross_context_pairs": len(truths),
            "cross_context_candidates_evaluated": cross_context_candidates,
            "labels_blinded_from_ranking": True,
            "compile_probes": compile_probes,
        }
    finally:
        # The only deleted target is the exact mktemp directory created above.
        shutil.rmtree(temporary)


def _build_current_fixture_archive(legacy: Path, cohort: FixtureCohort) -> tuple[list[dict[str, list[str]]], list[dict[str, str]]]:
    connection = sqlite3.connect(legacy)
    current = CategoryStore(connection)
    truths: list[dict[str, str]] = []
    try:
        for case in cohort.rankings:
            relevant_id = current.add_cell(f"{case.query} {case.direct_query} reference", context={"evaluation": case.domain})
            noise_id = current.add_cell(f"{case.query} {case.query} distractor", context={"evaluation": case.domain})
            current.compose(noise_id, relevant_id, "fixture association", context={"evaluation": case.domain})
            truths.append({"domain": case.domain, "relevant_id": relevant_id, "noise_id": noise_id,
                           "query": case.query, "direct_query": case.direct_query})
        for index, truth in enumerate(truths):
            current.compose(truth["noise_id"], truth["relevant_id"], "within-context association", context={"evaluation": truth["domain"]})
            foreign = truths[(index + 1) % len(truths)]
            truth["foreign_relevant_id"] = foreign["relevant_id"]
            current.compose(truth["noise_id"], foreign["relevant_id"], "cross-context association", context={"evaluation": truth["domain"]})
        cells = current.cells_at_level(0)
        return [
            {"query": _lexical_rank(case["query"], cells), "direct": _lexical_rank(case["direct_query"], cells)}
            for case in truths
        ], truths
    finally:
        connection.close()


def _compile_shadow_rankings(
    database: Path, epoch_id: str, truths: Sequence[dict[str, str]], baseline_rows: Sequence[dict[str, list[str]]],
) -> tuple[list[tuple[list[str], set[str]]], list[tuple[list[str], set[str]]], list[dict[str, object]], int]:
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    compiler = CategoryCompiler(store, CompileBudget())
    try:
        rankings: list[tuple[list[str], set[str]]] = []
        direct_rankings: list[tuple[list[str], set[str]]] = []
        probes: list[dict[str, object]] = []
        cross_context_candidates = 0
        for truth, baseline in zip(truths, baseline_rows, strict=True):
            context_id = store.create_context({"evaluation": "ranking", "domain": truth["domain"]})
            # Fixed label-blind transform of observed baseline rank.  Truth IDs
            # are not consulted until the completed compiler ranking is scored.
            for rank, raw_id in enumerate(baseline["query"], start=1):
                store.observe_weight(legacy_proxy_id(raw_id), context_id,
                                     WeightVector(1.0 / rank, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            query_compiled, query_probe = _timed_compile(
                compiler, epoch_id, context_id, legacy_proxy_id(baseline["query"][0]), "query",
            )
            ranked = [cell.id for cell in query_compiled.cells]
            foreign_relevant_id = legacy_proxy_id(truth["foreign_relevant_id"])
            cross_context_candidates += int(foreign_relevant_id in ranked)
            rankings.append((ranked, {legacy_proxy_id(truth["relevant_id"])}))
            probes.append(query_probe)
            direct_compiled, direct_probe = _timed_compile(
                compiler, epoch_id, context_id, legacy_proxy_id(baseline["direct"][0]), "direct",
            )
            direct_ranked = [cell.id for cell in direct_compiled.cells]
            direct_rankings.append((direct_ranked, {legacy_proxy_id(truth["relevant_id"])}))
            probes.append(direct_probe)
        return rankings, direct_rankings, probes, cross_context_candidates
    finally:
        compiler.close()
        store.close()


def _false_cross_context_transfers(
    rankings: Sequence[tuple[list[str], set[str]]], truths: Sequence[dict[str, str]],
) -> list[bool]:
    """One evaluable opportunity per fixture with a known foreign candidate.

    Empty results and same-context distractors are not false transfers.  A
    false transfer is specifically a foreign candidate before local relevance.
    """
    outcomes: list[bool] = []
    for ranking, relevant, truth in zip(rankings, (entry[1] for entry in rankings), truths, strict=True):
        foreign = legacy_proxy_id(truth["foreign_relevant_id"])
        if foreign not in ranking:
            continue
        local_position = min((index for index, item in enumerate(ranking) if item in relevant), default=None)
        foreign_position = ranking.index(foreign)
        outcomes.append(local_position is None or foreign_position < local_position)
    return outcomes


def _timed_compile(
    compiler: CategoryCompiler, epoch_id: str, context_id: str, seed_id: str, purpose: str,
) -> tuple[object, dict[str, object]]:
    started = time.monotonic_ns()
    compiled = compiler.compile(epoch_id, context_id=context_id, seed_cell_ids=(seed_id,))
    elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
    return compiled, {
        "purpose": purpose,
        "candidate_count": compiled.candidate_count,
        "token_count": compiled.token_count,
        "truncated": compiled.truncated,
        "elapsed_wall_time_ms": elapsed_ms,
    }


def _lexical_rank(query: str, cells: Sequence[dict]) -> list[str]:
    terms = tuple(term.casefold() for term in query.split() if term)
    scored = []
    for index, cell in enumerate(cells):
        content_terms = [term.casefold() for term in str(cell["content"]).split()]
        score = sum(content_terms.count(term) for term in terms)
        scored.append((score, index, str(cell["id"])))
    return [identifier for score, _index, identifier in sorted(scored, key=lambda row: (-row[0], row[1])) if score]


def _replay_three_times(legacy: Path, work_dir: Path) -> tuple[list[str], list[dict[str, object]], dict[str, object]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    replay_hashes: list[str] = []
    import_reports: list[dict[str, object]] = []
    probe: dict[str, object] | None = None
    for attempt in range(1, 4):
        output = (work_dir / f"replay-{attempt}" / "categories_v2.db").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise ValueError(f"refusing to overwrite existing disposable output: {output}")
        imported = import_legacy_category(legacy, output)
        import_report = asdict(imported)
        import_reports.append(import_report)
        replay_hashes.append(_full_state_digest(output, import_report))
        if probe is None:
            probe = _compile_probe(output, imported.root_epoch_id)
    assert probe is not None
    return replay_hashes, import_reports, probe


def _full_state_digest(database: Path, import_report: dict[str, object]) -> str:
    """Digest immutable replay state, not merely the active snapshot identities.

    Ordered row content covers cells, boundaries, contexts, events, weights,
    rewrites, epochs and snapshots.  Timestamp-only runtime fields are excluded
    because independent deterministic replays legitimately stamp different UTC
    creation times.
    """
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cat_%' ORDER BY name"
        ) if not str(row[0]).startswith("cat_vectors")]
        state: dict[str, object] = {"import_report": import_report, "tables": {}}
        for table in tables:
            columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
                       if str(row[1]) not in {"created_at", "applied_at"}]
            rows = connection.execute(
                f'SELECT {",".join(chr(34)+column+chr(34) for column in columns)} FROM "{table}" ORDER BY rowid'
            ).fetchall()
            state["tables"][table] = {"columns": columns, "rows": [list(row) for row in rows]}
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_value)
        return hashlib.sha256(payload.encode()).hexdigest()
    finally:
        connection.close()


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"blob": value.hex()}
    raise TypeError(type(value).__name__)


def _compile_probe(database: Path, epoch_id: str) -> dict[str, object]:
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    compiler = CategoryCompiler(store, CompileBudget())
    try:
        row = connection.execute(
            "SELECT id FROM cat_cells ORDER BY id LIMIT 1"
        ).fetchone()
        started = time.monotonic_ns()
        compiled = compiler.compile(epoch_id, seed_cell_ids=(() if row is None else (str(row[0]),)))
        elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
        return {
            "candidate_count": compiled.candidate_count,
            "cell_count": len(compiled.cells),
            "token_count": compiled.token_count,
            "truncated": compiled.truncated,
            "rotation_required": compiled.rotation_required,
            "elapsed_wall_time_ms": elapsed_ms,
        }
    finally:
        compiler.close()
        store.close()


def _acceptance(report: dict[str, object]) -> dict[str, object]:
    boundary = report["boundary_metrics"]
    assert isinstance(boundary, dict)
    overall = boundary["overall"]
    assert isinstance(overall, dict)
    ranking = report["ranking"]
    assert isinstance(ranking, dict)
    relative = ranking["relative_mrr_improvement"]
    import_report = report["import_report"]
    compiler_probe = report.get("compiler_probe")
    compiler_probes = report.get("compiler_probes", [])
    limits = report.get("compiler_limits")
    resource_benchmark = report["resource_benchmark"]
    import_reports = report.get("import_reports")
    replay_losses = None if not isinstance(import_reports, list) else [int(item["unexplained_loss"]) for item in import_reports]
    compiler_conformant = (
        isinstance(compiler_probes, list)
        and bool(compiler_probes)
        and all(
            isinstance(probe, dict)
            and int(probe["candidate_count"]) <= 50_000
            and int(probe["token_count"]) <= 65_536
            and float(probe["elapsed_wall_time_ms"]) <= 500
            for probe in compiler_probes
        )
        and isinstance(limits, dict)
        and all(limits.get(name) == value for name, value in {
            "max_depth": 4, "max_neighbors": 64, "max_candidates": 50_000,
            "wall_time_ms": 500, "hard_ceiling": 65_536,
        }.items())
    )
    resource_evaluated = isinstance(resource_benchmark, dict) and bool(resource_benchmark.get("acceptance_gate", {}).get("evaluated"))
    resource_observed = None if not isinstance(resource_benchmark, dict) else resource_benchmark.get("incremental_peak_rss_bytes")
    resource_passed = resource_evaluated and isinstance(resource_observed, int) and resource_observed < RSS_GATE_BYTES
    gates = {
        "boundary_overall_f1": _gate(GATE_THRESHOLDS["boundary_overall_f1"], overall["f1"], float(overall["f1"]) >= 0.80),
        "cross_context_relative_mrr_improvement": _gate(
            GATE_THRESHOLDS["cross_context_relative_mrr_improvement"], relative,
            relative is not None and float(relative) >= 0.15,
        ),
        "direct_recall_regression": _gate(
            GATE_THRESHOLDS["direct_recall_regression"],
            ranking["direct_recall_regression"] if ranking.get("direct_recall_evaluated") else None,
            ranking.get("direct_recall_evaluated") is True and float(ranking["direct_recall_regression"]) <= 0.05,
        ),
        "false_transfer_rate": _gate(
            GATE_THRESHOLDS["false_transfer_rate"], ranking["false_transfer_rate"],
            ranking.get("false_transfer_evaluated") is True and float(ranking["false_transfer_rate"]) <= 0.10,
        ),
        "identical_replay_hashes": _gate(
            GATE_THRESHOLDS["identical_replay_hashes"], len(report["replay_hashes"]), bool(report["replay_identical"]),
        ),
        "unexplained_replay_loss": _gate(
            GATE_THRESHOLDS["unexplained_replay_loss"], replay_losses,
            replay_losses is not None and len(replay_losses) == 3 and all(loss == 0 for loss in replay_losses),
        ),
        "compiler_conformance": _gate(
            {"max_candidates": 50_000, "hard_ceiling_tokens": 65_536,
             "max_wall_time_ms": GATE_THRESHOLDS["compiler_conformance_wall_time_ms"]},
            compiler_probes, compiler_conformant,
        ),
        "incremental_peak_rss": _gate(
            GATE_THRESHOLDS["incremental_peak_rss_bytes"], resource_observed, resource_passed,
        ),
    }
    return {"thresholds": GATE_THRESHOLDS, "gates": gates, "overall_pass": all(gate["passed"] for gate in gates.values())}


def _gate(threshold: object, observed: object, passed: bool) -> dict[str, object]:
    return {"threshold": threshold, "observed": observed, "passed": passed}


RSS_GATE_BYTES = 1 << 30


def _resource_benchmark(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        report = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"resource-report is not valid JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError("resource-report must be a JSON object")
    if report.get("cells") != 1_000_000:
        raise ValueError("resource-report must be from --cells 1000000")
    if report.get("acceptance_run") is not True:
        raise ValueError("resource-report must be an acceptance_run")
    if report.get("streaming") is not True or report.get("batch_size") != 10_000:
        raise ValueError("resource-report must prove 10000-cell streaming")
    compiler = report.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("ran") is not True:
        raise ValueError("resource-report must prove a compiler run")
    gate = report.get("acceptance_gate")
    if not isinstance(gate, dict) or gate.get("evaluated") is not True:
        raise ValueError("resource-report does not contain an evaluated acceptance gate")
    if gate.get("threshold_bytes") != RSS_GATE_BYTES:
        raise ValueError("resource-report uses a different RSS threshold")
    observed = report.get("incremental_peak_rss_bytes")
    if type(observed) is not int or observed < 0:
        raise ValueError("resource-report RSS must be a non-negative finite integer")
    if gate.get("observed_bytes") != observed:
        raise ValueError("resource-report gate RSS does not match observed RSS")
    expected_pass = observed < RSS_GATE_BYTES
    if gate.get("passed") is not expected_pass:
        raise ValueError("resource-report gate pass value is inconsistent with RSS")
    baseline = report.get("baseline_peak_rss_bytes")
    peak = report.get("peak_rss_bytes")
    if type(baseline) is not int or type(peak) is not int or baseline < 0 or peak < baseline:
        raise ValueError("resource-report peak RSS values are invalid")
    if observed != peak - baseline:
        raise ValueError("resource-report RSS increment is inconsistent with peak values")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        report = run_evaluation(args)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
