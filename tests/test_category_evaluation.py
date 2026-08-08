"""Behavioral checks for the evolving-category acceptance harness."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import math
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.category_evolution import runner as evaluation_runner
from experiments.category_evolution.fixtures import fixture_cohort, fixture_hash
from experiments.category_evolution.metrics import (
    boundary_metrics,
    direct_recall_regression,
    false_transfer_rate,
    mean_reciprocal_rank,
    relative_mrr_improvement,
)
from experiments.category_evolution.runner import main as runner_main
from experiments.category_evolution.runner import _acceptance, _full_state_digest
from category_context import ContextTracker


def test_boundary_metrics_by_kind():
    """A missed gradual boundary must lower recall without creating a false positive."""
    rows = [
        ("explicit", True, True), ("abrupt", True, True),
        ("gradual", True, False), ("gradual", False, False),
    ]
    result = boundary_metrics(rows)
    assert result["overall"]["precision"] == 1.0
    assert result["overall"]["recall"] == pytest.approx(2 / 3)
    assert result["overall"]["f1"] == pytest.approx(0.8)
    assert set(result) == {"overall", "explicit", "abrupt", "gradual"}


def test_ranking_metrics_and_empty_semantics_are_deterministic():
    """A ranking with no relevant hit contributes zero, while empty cohorts are explicit."""
    rankings = [(["a", "b"], {"b"}), (["c", "d"], {"c"}), (["x"], {"z"})]
    assert mean_reciprocal_rank(rankings) == pytest.approx(0.5)
    assert mean_reciprocal_rank([]) == 0.0
    assert false_transfer_rate([True, False, False, True]) == 0.5
    assert false_transfer_rate([]) == 0.0
    assert direct_recall_regression(0, 0) == 0.0
    assert direct_recall_regression(10, 9) == 0.1
    assert relative_mrr_improvement(0.0, 0.2) is None


def test_metrics_reject_malformed_rows_and_rankings():
    """Malformed measurement input must fail rather than produce a misleading score."""
    with pytest.raises(ValueError, match="boundary kind"):
        boundary_metrics([("unknown", True, True)])
    with pytest.raises(ValueError, match="ranking"):
        mean_reciprocal_rank([(["a", "a"], {"a"})])
    with pytest.raises(ValueError, match="bool"):
        false_transfer_rate([1])


def test_fixture_cohorts_are_deterministic_and_vocabulary_isolated():
    """A cohort hash changes for its distinct words but not process/order variation."""
    development = fixture_cohort("development", seed=20260807)
    holdout = fixture_cohort("holdout", seed=20260807)
    assert fixture_hash(development) == "dab094fab673bec72b30bd89af20590baddf9c5c2408dec240a5f961f634c241"
    assert fixture_hash(development) == fixture_hash(fixture_cohort("development", seed=20260807))
    assert fixture_hash(development) != fixture_hash(holdout)
    assert {case.domain for case in development.cases} == {
        "conversation", "coding", "reading_media", "planning",
    }
    assert {case.structure for case in development.cases} == {
        case.structure for case in holdout.cases
    }
    assert set(development.vocabulary).isdisjoint(holdout.vocabulary)
    assert {
        "return-to-prior", "overlap-control", "source-only-control", "fork-reconciliation",
    }.issubset({case.structure for case in development.cases})


def test_fixture_hash_is_identical_in_a_separate_python_process():
    """Canonical serialization must not depend on a process's set/dict iteration order."""
    completed = subprocess.run(
        [sys.executable, "-c", (
            "from experiments.category_evolution.fixtures import fixture_cohort, fixture_hash; "
            "print(fixture_hash(fixture_cohort('development', seed=20260807)))"
        )],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "dab094fab673bec72b30bd89af20590baddf9c5c2408dec240a5f961f634c241"


def test_abrupt_and_gradual_fixture_transitions_exercise_different_tracker_paths():
    """An abrupt case must be strong evidence; gradual evidence must use confirmation."""
    cases = fixture_cohort("development").cases
    abrupt = next(case for case in cases if case.structure == "confirmed-abrupt-change")
    gradual = next(case for case in cases if case.structure == "confirmed-gradual-change")
    abrupt_tracker = ContextTracker()
    abrupt_tracker.observe(abrupt.observations[0])
    gradual_tracker = ContextTracker()
    gradual_tracker.observe(gradual.observations[0])
    assert abrupt_tracker.observe(abrupt.observations[1]).score >= 0.65
    assert 0.35 <= gradual_tracker.observe(gradual.observations[1]).score < 0.65


def _legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cells (
            id TEXT PRIMARY KEY, level INTEGER NOT NULL, source_id TEXT, target_id TEXT,
            content TEXT NOT NULL, context TEXT, created_at TEXT NOT NULL,
            accessed_at TEXT, access_count INTEGER
        );
        INSERT INTO cells VALUES
          ('a', 0, NULL, NULL, 'first', '{}', '2020-01-01T00:00:00+00:00', NULL, 0),
          ('b', 0, NULL, NULL, 'second', '{}', '2020-01-01T00:00:00+00:00', NULL, 0),
          ('edge', 1, 'a', 'b', 'link', '{}', '2020-01-01T00:00:00+00:00', NULL, 0);
        """
    )
    connection.commit()
    connection.close()


def test_runner_replays_real_legacy_database_three_times_without_mutating_it(tmp_path, capsys):
    """The runner reports real independent replay hashes and preserves legacy bytes."""
    legacy = tmp_path / "categories.db"
    _legacy_database(legacy)
    before = legacy.read_bytes()
    work = tmp_path / "evaluation"
    assert runner_main(["--legacy", str(legacy), "--work-dir", str(work), "--cohort", "development", "--seed", "20260807"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["replay_hashes"][0] == report["replay_hashes"][1] == report["replay_hashes"][2]
    assert report["replay_identical"] is True
    assert report["ranking"]["source"] == "category_compiler_fixture_db"
    assert report["ranking"]["baseline_source"] == "CategoryStore.search"
    assert report["ranking_blinded"] is True
    assert report["blind_corpus"]["schema"] == "engram.category-evolution.blind-corpus"
    assert report["adjudication"]["schema"] == "engram.category-evolution.adjudication"
    assert report["ranking_output"]["schema"] == "engram.category-evolution.ranking-output"
    assert report["blind_corpus"]["hash"] != report["adjudication"]["hash"]
    assert report["boundary_metrics"]["overall"]["count"] == sum(
        len(case.expected_decisions) for case in fixture_cohort("development").cases
    )
    assert {name: report["compiler_limits"][name] for name in (
        "max_depth", "max_neighbors", "max_candidates", "wall_time_ms", "hard_ceiling",
    )} == {"max_depth": 4, "max_neighbors": 64, "max_candidates": 50_000,
          "wall_time_ms": 500, "hard_ceiling": 65_536}
    assert report["ranking"]["direct_seed_source"] == "baseline_direct_top"
    assert report["ranking"]["cross_context_pairs"] == 4
    assert report["ranking"]["cross_context_candidates_evaluated"] > 0
    assert len(report["ranking"]["compile_probes"]) == 8
    assert report["acceptance"]["gates"]["unexplained_replay_loss"]["passed"] is True
    assert report["configuration"]["shadow"] is True
    assert report["ranking_provenance"] == (
        "validated blind subprocess over a controlled disposable fixture archive"
    )
    assert report["acceptance"]["gates"]["incremental_peak_rss"]["passed"] is False
    assert report["acceptance"]["overall_pass"] is False
    assert legacy.read_bytes() == before
    assert not (work / "categories_v2.db").exists()


@pytest.mark.parametrize("override", [
    ("--soft-threshold", "0.10"),
    ("--hard-threshold", "0.90"),
    ("--hard-confirmations", "3"),
])
def test_holdout_refuses_every_tuning_override(tmp_path, capsys, override):
    """Holdout options are rejected instead of silently tuning the measured result."""
    legacy = tmp_path / "categories.db"
    _legacy_database(legacy)
    assert runner_main([
        "--legacy", str(legacy), "--work-dir", str(tmp_path / "out"),
        "--cohort", "holdout", *override,
    ]) == 2
    assert "holdout rejects tuning" in capsys.readouterr().err


def test_replay_loss_is_a_failed_gate_not_a_successful_stable_hash(tmp_path, capsys):
    """Identical imports with unexplained loss must not claim replay acceptance."""
    legacy = tmp_path / "lossy-categories.db"
    _legacy_database(legacy)
    connection = sqlite3.connect(legacy)
    connection.execute(
        "INSERT INTO cells VALUES (?, 2, ?, ?, ?, ?, ?, ?, ?)",
        ("lost", "missing", "edge", "unimportable", "{}", "2020-01-01T00:00:00+00:00", None, 0),
    )
    connection.commit()
    connection.close()
    assert runner_main(["--legacy", str(legacy), "--work-dir", str(tmp_path / "out"), "--cohort", "development"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["replay_identical"] is True
    assert report["import_report"]["unexplained_loss"] == 1
    assert [item["unexplained_loss"] for item in report["import_reports"]] == [1, 1, 1]
    assert report["acceptance"]["gates"]["unexplained_replay_loss"]["observed"] == [1, 1, 1]
    assert report["acceptance"]["gates"]["unexplained_replay_loss"]["passed"] is False
    assert report["acceptance"]["overall_pass"] is False


def test_runner_rejects_incomplete_resource_artifact(tmp_path, capsys):
    """A hand-written RSS number cannot stand in for the streamed 1M benchmark."""
    legacy = tmp_path / "categories.db"
    _legacy_database(legacy)
    resource_report = tmp_path / "resource.json"
    resource_report.write_text(json.dumps({
        "cells": 1_000_000, "acceptance_run": True,
        "incremental_peak_rss_bytes": 1,
        "acceptance_gate": {"evaluated": True, "threshold_bytes": 1 << 30},
    }))
    assert runner_main([
        "--legacy", str(legacy), "--work-dir", str(tmp_path / "out"),
        "--cohort", "development", "--resource-report", str(resource_report),
    ]) == 2
    assert "resource-report" in capsys.readouterr().err


def test_small_resource_benchmark_streams_and_marks_acceptance_gate_unevaluated(tmp_path):
    """A 1,000-cell shape check cannot be presented as the required 1M resource result."""
    from experiments.category_evolution.benchmark import run_benchmark

    report = run_benchmark(cells=1_000, work_dir=tmp_path)
    assert report["cells"] == 1_000
    assert report["batch_size"] == 10_000
    assert report["compiler"]["ran"] is True
    assert report["incremental_peak_rss_bytes"] >= 0
    assert report["acceptance_gate"] == {
        "threshold_bytes": 1 << 30,
        "observed_bytes": report["incremental_peak_rss_bytes"],
        "evaluated": False,
        "passed": False,
        "reason": "requires explicit --cells 1000000",
    }
    assert report["acceptance_run"] is False
    assert report["compiler"]["candidate_count"] == 41
    assert report["compiler"]["max_hops"] == 4
    assert report["topology"] == {
        "valid": True,
        "object_cells": 501,
        "edge_cells": 499,
        "boundary_rows": 998,
    }
    assert "elapsed_wall_time_ms" in report["compiler"]
    assert len(report["snapshot_content_hash"]) == 64
    assert list(tmp_path.iterdir()) == []


def test_resource_worker_cannot_accept_or_mutate_a_caller_database(tmp_path):
    """The importable child entry point owns its database and has no path parameter."""
    from experiments.category_evolution.benchmark import _worker

    target = tmp_path / "sentinel.db"
    target.write_bytes(b"do-not-touch")
    before = target.read_bytes()
    with pytest.raises(TypeError):
        _worker(1, target)
    assert target.read_bytes() == before


def test_resource_neighbor_observation_is_derived_from_actual_compiled_frontier(monkeypatch):
    """A disconnected/empty compiler result cannot inherit degree from the fixture graph."""
    from experiments.category_evolution import benchmark

    monkeypatch.setattr(
        benchmark.CategoryCompiler,
        "compile",
        lambda self, epoch_id, **kwargs: SimpleNamespace(
            candidate_count=0,
            cells=(),
            token_count=0,
            truncated=False,
            rotation_required=False,
        ),
    )
    report = benchmark._worker(1_000)
    assert report["compiler"]["cell_count"] == 0
    assert report["compiler"]["raw_max_neighbors"] == 0
    assert report["compiler"]["max_neighbors_observed"] == 0
    assert report["compiler"]["neighbor_limit_hit"] is False


def test_resource_acceptance_requires_the_complete_nontrivial_frontier():
    """A low-RSS million-cell no-op compiler result cannot pass acceptance."""
    from experiments.category_evolution.benchmark import _benchmark_acceptance

    report = {
        "incremental_peak_rss_bytes": 1,
        "compiler": {"candidate_count": 0, "max_hops": 0},
    }
    gate = _benchmark_acceptance(1_000_000, report)
    assert gate["evaluated"] is True
    assert gate["passed"] is False
    assert "frontier" in gate["reason"]


def _passing_resource_report():
    from experiments.category_evolution.benchmark import BENCHMARK_OUTPUT_SCHEMA

    return {
        "schema": BENCHMARK_OUTPUT_SCHEMA,
        "schema_version": 1,
        "cells": 1_000_000,
        "batch_size": 10_000,
        "streaming": True,
        "rss_platform_semantics": "ru_maxrss peak high-water mark in bytes",
        "baseline_peak_rss_bytes": 1,
        "peak_rss_bytes": 2,
        "incremental_peak_rss_bytes": 1,
        "snapshot_content_hash": "a" * 64,
        "topology": {
            "valid": True,
            "object_cells": 500_001,
            "edge_cells": 499_999,
            "boundary_rows": 999_998,
        },
        "compiler": {
            "purpose": "resource_benchmark",
            "ran": True,
            "candidate_count": 41,
            "cell_count": 41,
            "truncated": True,
            "rotation_required": False,
            "token_count": 41,
            "elapsed_wall_time_ms": 1.0,
            "max_hops": 4,
            "max_neighbors_observed": 5,
            "raw_max_neighbors": 5,
            "neighbor_limit_hit": False,
        },
        "acceptance_gate": {
            "threshold_bytes": 1 << 30,
            "observed_bytes": 1,
            "evaluated": True,
            "passed": True,
            "reason": "all resource and compiler limits satisfied",
        },
        "acceptance_run": True,
    }


@pytest.mark.parametrize(("field", "value"), [
    ("ran", False),
    ("max_hops", 5),
    ("max_neighbors_observed", 65),
    ("candidate_count", 50_001),
    ("elapsed_wall_time_ms", 501.0),
    ("token_count", 65_537),
])
def test_resource_benchmark_requires_run_and_every_compiler_cap(field, value):
    """Low RSS cannot conceal missing or over-budget million-cell compiler evidence."""
    from experiments.category_evolution.benchmark import _benchmark_acceptance

    report = _passing_resource_report()
    report["compiler"][field] = value
    gate = _benchmark_acceptance(1_000_000, report)
    assert gate["evaluated"] is True
    assert gate["passed"] is False


def test_resource_compiler_observation_participates_in_overall_conformance():
    """Unrelated small compiles cannot mask an invalid million-cell compile."""
    report = _passing_acceptance_report()
    report["resource_benchmark"]["compiler"]["token_count"] = 65_537
    report["resource_benchmark"]["acceptance_gate"]["passed"] = False
    acceptance = _acceptance(report)
    assert acceptance["gates"]["compiler_conformance"]["passed"] is False
    assert acceptance["gates"]["incremental_peak_rss"]["passed"] is False
    assert acceptance["overall_pass"] is False


def test_full_state_digest_changes_for_content_boundary_context_and_loss(tmp_path):
    """Same active IDs cannot hide immutable replay-state changes."""
    database = tmp_path / "v2.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE cat_cells (id TEXT, content TEXT, created_at TEXT);
        CREATE TABLE cat_boundaries (cell_id TEXT, boundary_id TEXT, created_at TEXT);
        CREATE TABLE cat_contexts (id TEXT, features_json TEXT, created_at TEXT);
        INSERT INTO cat_cells VALUES ('same', 'one', 'now');
        INSERT INTO cat_boundaries VALUES ('same', 'other', 'now');
        INSERT INTO cat_contexts VALUES ('ctx', '{}', 'now');
    """)
    connection.commit(); connection.close()
    original = _full_state_digest(database, {"unexplained_loss": 0})
    connection = sqlite3.connect(database)
    connection.execute("UPDATE cat_cells SET content='two'")
    connection.commit(); connection.close()
    assert _full_state_digest(database, {"unexplained_loss": 0}) != original
    connection = sqlite3.connect(database)
    connection.execute("UPDATE cat_cells SET content='one'")
    connection.commit(); connection.close()
    assert _full_state_digest(database, {"unexplained_loss": 1}) != original
    connection = sqlite3.connect(database)
    connection.execute("UPDATE cat_boundaries SET boundary_id='changed'")
    connection.commit(); connection.close()
    assert _full_state_digest(database, {"unexplained_loss": 0}) != original
    connection = sqlite3.connect(database)
    connection.execute("UPDATE cat_boundaries SET boundary_id='other'")
    connection.execute("UPDATE cat_contexts SET features_json='{\"changed\":true}'")
    connection.commit(); connection.close()
    assert _full_state_digest(database, {"unexplained_loss": 0}) != original


@pytest.mark.parametrize("table,column", [
    ("cat_schema_version", "version"),
    ("cat_events", "payload_json"),
    ("cat_weight_observations", "relevance"),
    ("cat_rewrites", "payload_json"),
    ("cat_rewrite_members", "external_id"),
    ("cat_epochs", "created_event_id"),
    ("cat_epoch_parents", "parent_id"),
    ("cat_snapshots", "content_hash"),
])
def test_full_state_digest_independently_covers_each_remaining_replay_table(tmp_path, table, column):
    """Every immutable replay table contributes independently to the digest."""
    database = tmp_path / f"{table}.db"
    connection = sqlite3.connect(database)
    connection.execute(f'CREATE TABLE "{table}" (id TEXT, "{column}" TEXT, created_at TEXT)')
    connection.execute(f'INSERT INTO "{table}" VALUES (?, ?, ?)', ("row", "before", "runtime"))
    connection.commit(); connection.close()
    original = _full_state_digest(database, {"unexplained_loss": 0})
    connection = sqlite3.connect(database)
    connection.execute(f'UPDATE "{table}" SET "{column}" = ?', ("after",))
    connection.commit(); connection.close()
    assert _full_state_digest(database, {"unexplained_loss": 0}) != original


def test_label_swap_changes_metrics_not_completed_ranking():
    """Truth is applied after ranking; changing it cannot change compiler candidates/scores."""
    completed_ranking = ["candidate-a", "candidate-b"]
    before = list(completed_ranking)
    assert mean_reciprocal_rank([(completed_ranking, {"candidate-a"})]) == 1.0
    assert mean_reciprocal_rank([(completed_ranking, {"candidate-b"})]) == 0.5
    assert completed_ranking == before


def test_compiler_rank_perturbation_changes_shadow_metric():
    """A changed compiler ordering must change the resulting shadow metric."""
    assert mean_reciprocal_rank([(["relevant", "other"], {"relevant"})]) == 1.0
    assert mean_reciprocal_rank([(["other", "relevant"], {"relevant"})]) == 0.5


def test_changed_blind_query_changes_real_baseline_and_compiler_output():
    """A non-gold input perturbation reaches real search and the downstream compiler."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    original = evaluation_runner._run_blinded_ranking(corpus)
    perturbed = copy.deepcopy(corpus)
    perturbed["cases"][0]["query_text"] = perturbed["cases"][0]["direct_query_text"]
    perturbed["fixture_hash"] = evaluation_runner._blind_manifest_hash(perturbed)
    changed = evaluation_runner._run_blinded_ranking(perturbed)
    assert changed["rankings"][0]["baseline"] != original["rankings"][0]["baseline"]
    assert changed["rankings"][0]["shadow"] != original["rankings"][0]["shadow"]


def test_zero_direct_and_transfer_evidence_is_not_evaluable():
    """Missing evidence must fail acceptance rather than score as perfect zero regression."""
    report = {
        "boundary_metrics": {"overall": {"f1": 1.0}},
        "ranking": {"relative_mrr_improvement": None, "direct_recall_baseline_hits": 0,
                    "direct_recall_regression": 0.0, "direct_recall_evaluated": False,
                    "false_transfer_rate": None, "false_transfer_evaluated": False},
        "import_report": None, "import_reports": None, "replay_hashes": [], "replay_identical": False,
        "compiler_probe": None, "compiler_probes": [], "compiler_limits": {}, "resource_benchmark": None,
    }
    acceptance = _acceptance(report)
    assert acceptance["gates"]["direct_recall_regression"]["observed"] is None
    assert acceptance["gates"]["direct_recall_regression"]["passed"] is False
    assert acceptance["gates"]["false_transfer_rate"]["passed"] is False
    assert acceptance["overall_pass"] is False


def _passing_acceptance_report():
    probe = {
        "purpose": "query", "candidate_count": 10, "cell_count": 10,
        "token_count": 100, "truncated": False, "rotation_required": False,
        "elapsed_wall_time_ms": 1.0, "max_hops": 4, "max_neighbors_observed": 4,
        "raw_max_neighbors": 4, "neighbor_limit_hit": False,
    }
    return {
        "ranking_blinded": True,
        "boundary_metrics": {"overall": {"f1": 1.0}},
        "ranking": {
            "relative_mrr_improvement": 0.2,
            "direct_recall_regression": 0.0,
            "direct_recall_evaluated": True,
            "false_transfer_rate": 0.0,
            "false_transfer_evaluated": True,
        },
        "import_report": {"unexplained_loss": 0},
        "import_reports": [{"unexplained_loss": 0}] * 3,
        "replay_hashes": ["same"] * 3,
        "replay_identical": True,
        "compiler_probe": probe,
        "compiler_probes": [probe],
        "compiler_limits": {
            "max_depth": 4, "max_neighbors": 64, "max_candidates": 50_000,
            "wall_time_ms": 500, "hard_ceiling": 65_536,
        },
        "resource_benchmark": _passing_resource_report(),
    }


@pytest.mark.parametrize("limit,value", [
    ("max_depth", 3), ("max_neighbors", 63), ("max_candidates", 49_999),
    ("wall_time_ms", 499), ("hard_ceiling", 65_535),
])
def test_each_compiler_cap_is_exact_and_acceptance_sensitive(limit, value):
    """Changing any one configured cap invalidates compiler conformance."""
    report = _passing_acceptance_report()
    assert _acceptance(report)["overall_pass"] is True
    report["compiler_limits"][limit] = value
    acceptance = _acceptance(report)
    assert acceptance["gates"]["compiler_conformance"]["passed"] is False
    assert acceptance["overall_pass"] is False


@pytest.mark.parametrize("observation,value", [
    ("max_hops", 5), ("max_neighbors_observed", 65), ("candidate_count", 50_001),
    ("elapsed_wall_time_ms", 501.0), ("token_count", 65_537),
])
def test_each_effective_compiler_observation_is_acceptance_sensitive(observation, value):
    """A runtime violation of any one of the five caps fails the compiler gate."""
    report = _passing_acceptance_report()
    report["compiler_probes"][0][observation] = value
    acceptance = _acceptance(report)
    assert acceptance["gates"]["compiler_conformance"]["passed"] is False
    assert acceptance["overall_pass"] is False


def test_valid_hub_reports_effective_neighbor_cap_and_remains_conformant(tmp_path):
    """Raw degree 65 is distinct from the compiler's admitted-neighbor maximum of 64."""
    from categories import Boundary, CellDraft, EvolvingCategoryStore
    from category_evolution import EvolutionEngine

    database = tmp_path / "hub.db"
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    active_ids = ["a-hub"]
    store.create_cell(CellDraft("a-hub", 0, "hub"))
    for index in range(65):
        target_id = f"z-target-{index:02d}"
        edge_id = f"m-edge-{index:02d}"
        store.create_cell(CellDraft(target_id, 0, f"target {index}"))
        store.create_cell(CellDraft(
            edge_id, 1, f"edge {index}",
            boundaries=(
                Boundary("source", 0, "a-hub"),
                Boundary("target", 0, target_id),
            ),
        ))
        active_ids.extend((target_id, edge_id))
    EvolutionEngine(store).create_root_epoch("root", active_ids)
    store.close()

    probe = evaluation_runner._compile_probe(database, "root")
    assert probe["raw_max_neighbors"] == 65
    assert probe["max_neighbors_observed"] == 64
    assert probe["neighbor_limit_hit"] is True
    assert probe["truncated"] is True
    report = _passing_acceptance_report()
    report["compiler_probe"] = probe
    report["compiler_probes"] = [probe]
    assert _acceptance(report)["gates"]["compiler_conformance"]["passed"] is True


@pytest.mark.parametrize("missing,gate", [
    ("relative", "cross_context_relative_mrr_improvement"),
    ("direct", "direct_recall_regression"),
    ("transfer", "false_transfer_rate"),
])
def test_each_missing_ranking_evidence_independently_fails_acceptance(missing, gate):
    """No unrelated failed gate can conceal missing ranking evidence."""
    report = _passing_acceptance_report()
    assert _acceptance(report)["overall_pass"] is True
    if missing == "relative":
        report["ranking"]["relative_mrr_improvement"] = None
    elif missing == "direct":
        report["ranking"]["direct_recall_evaluated"] = False
    else:
        report["ranking"]["false_transfer_rate"] = None
        report["ranking"]["false_transfer_evaluated"] = False
    acceptance = _acceptance(report)
    assert acceptance["gates"][gate]["passed"] is False
    assert acceptance["overall_pass"] is False


def test_false_transfer_uses_explicit_foreign_opportunities_and_zero_is_unevaluable():
    """The denominator is annotated opportunity truth; absent truth is not a perfect zero."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    no_opportunities = copy.deepcopy(adjudication)
    for case in no_opportunities["ranking_cases"]:
        case["negative_transfer_opportunities"] = []
        case["negative_transfer_truth"] = {}
    unscored = evaluation_runner._score_ranking_output(output, no_opportunities, corpus)
    assert unscored["false_transfer_evaluated"] is False
    assert unscored["false_transfer_rate"] is None

    forced = copy.deepcopy(output)
    gold = adjudication["ranking_cases"][0]
    foreign = gold["negative_transfer_opportunities"][0]
    relevant = gold["relevant_ids"][0]
    ranking = forced["rankings"][0]["shadow"]
    by_id = {row["candidate_id"]: row for row in ranking}
    assert foreign in by_id and relevant in by_id
    remainder = [row for row in ranking if row["candidate_id"] not in {foreign, relevant}]
    projected = [by_id[foreign], by_id[relevant], *remainder]
    projected_iterator = iter(projected)
    forced["rankings"][0]["compiler_cells"] = [
        next(projected_iterator) if row["candidate_id"] in by_id else row
        for row in forced["rankings"][0]["compiler_cells"]
    ]
    forced["rankings"][0]["shadow"] = projected
    scored = evaluation_runner._score_ranking_output(forced, adjudication, corpus)
    assert scored["false_transfer_evaluated"] is True
    assert scored["false_transfer_rate"] > 0.0


def test_missing_legacy_keeps_compiler_schema_and_acceptance_false(tmp_path, capsys):
    """Environmental replay absence is a stable report shape, never a passing gate."""
    assert runner_main(["--legacy", str(tmp_path / "none.db"), "--work-dir", str(tmp_path / "out"), "--cohort", "development"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["compiler_probe"] is None
    assert report["compiler_probes"] == report["ranking"]["compile_probes"]
    assert len(report["compiler_probes"]) == 8
    assert report["import_reports"] == []
    assert report["replay_digests"] == []
    assert report["acceptance"]["overall_pass"] is False


def _json_shape(value):
    if isinstance(value, dict):
        return {key: _json_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [len(value), *(_json_shape(item) for item in value)]
    return type(value).__name__


def test_missing_legacy_report_has_a_stable_complete_json_shape(tmp_path, capsys):
    """Absent replay evidence changes values, never the report contract."""
    reports = []
    for index in range(2):
        assert runner_main([
            "--legacy", str(tmp_path / "none.db"),
            "--work-dir", str(tmp_path / f"out-{index}"),
            "--cohort", "development",
        ]) == 0
        reports.append(json.loads(capsys.readouterr().out))
    assert _json_shape(reports[0]) == _json_shape(reports[1])


def test_one_intermediate_boundary_decision_mutation_changes_metrics():
    """Scoring consumes every expected decision, not only each trace's final state."""
    cohort = fixture_cohort("development")
    _corpus, adjudication = evaluation_runner._build_blinded_inputs(cohort)
    configuration = {
        "soft_threshold": 0.35, "hard_threshold": 0.65, "hard_confirmations": 2,
    }
    predictions = evaluation_runner._predict_boundary_decisions(cohort, configuration)
    original = evaluation_runner._score_boundary_predictions(predictions, adjudication)
    changed = copy.deepcopy(predictions)
    changed[0]["decisions"][0] = not changed[0]["decisions"][0]
    rescored = evaluation_runner._score_boundary_predictions(changed, adjudication)
    assert original["overall"]["count"] == 104
    assert rescored != original


def test_private_worker_cli_rejects_direct_invocation(tmp_path):
    """The public benchmark CLI cannot accept a worker database path."""
    result = subprocess.run([sys.executable, "-m", "experiments.category_evolution.benchmark", "--_worker", "--cells", "1", "--work-dir", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert not list(tmp_path.glob("*.db"))


def test_text_encoder_is_deterministic_normalized_and_semantic():
    """Changing labels cannot matter; shared text must create genuine cosine similarity."""
    first = evaluation_runner._fixture_vector("Alpha, beta beta!")
    repeated = evaluation_runner._fixture_vector("Alpha, beta beta!")
    shared = evaluation_runner._fixture_vector("beta alpha")
    disjoint = evaluation_runner._fixture_vector("quartz zephyr")
    assert first == repeated
    assert len(first) == 64
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)
    assert sum(left * right for left, right in zip(first, shared, strict=True)) > sum(
        left * right for left, right in zip(first, disjoint, strict=True)
    )


def test_blind_baseline_is_real_sqlite_vec_category_store_search(tmp_path):
    """Stored vectors and independent production searches reproduce the emitted baseline."""
    from categories import CategoryStore

    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    database = tmp_path / "current.db"
    emitted = evaluation_runner._build_current_blind_archive(database, corpus)
    connection = sqlite3.connect(database)
    evaluation_runner._load_vec(connection)
    store = CategoryStore(connection, dimension=64)
    try:
        level_zero_count = sum(candidate["dimension"] == 0 for candidate in corpus["candidates"])
        assert connection.execute("SELECT COUNT(*) FROM cell_vectors").fetchone()[0] == level_zero_count
        case = corpus["cases"][0]
        query_ids = [row["id"] for row in store.search(
            evaluation_runner._fixture_vector(case["query_text"]), level=0, limit=level_zero_count,
        )]
        direct_ids = [row["id"] for row in store.search(
            evaluation_runner._fixture_vector(case["direct_query_text"]), level=0, limit=level_zero_count,
        )]
        assert query_ids == [row["candidate_id"] for row in emitted[case["case_id"]]["baseline"]]
        assert direct_ids == [row["candidate_id"] for row in emitted[case["case_id"]]["direct"]]
        assert query_ids != direct_ids
    finally:
        connection.close()


def _json_keys_and_strings(value):
    keys: set[str] = set()
    strings: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            _item_keys, _item_strings = _json_keys_and_strings(item)
            keys.update(_item_keys)
            strings.update(_item_strings)
    elif isinstance(value, list):
        for item in value:
            _item_keys, _item_strings = _json_keys_and_strings(item)
            keys.update(_item_keys)
            strings.update(_item_strings)
    elif isinstance(value, str):
        strings.add(value)
    return keys, strings


def test_blind_corpus_json_excludes_gold_keys_and_values():
    """The serialized worker input contains observations, never adjudication roles or labels."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    corpus_keys, corpus_strings = _json_keys_and_strings(json.loads(json.dumps(corpus)))
    assert corpus_keys.isdisjoint({
        "relevant_id", "relevant_ids", "domain", "context_label", "candidate_context_labels",
        "negative_transfer_opportunities", "negative_transfer_truth", "expected_boundary",
        "expected_decisions", "acceptance", "truth", "expected_rank",
    })
    gold_context_labels = {
        label
        for case in adjudication["ranking_cases"]
        for label in case["candidate_context_labels"].values()
    }
    assert corpus_strings.isdisjoint(gold_context_labels)
    assert corpus_strings.isdisjoint({"explicit", "abrupt", "gradual"})


def test_blind_candidates_and_graph_are_permutation_symmetric_across_gold_roles():
    """Text and graph data leave at least two indistinguishable choices for every gold ID."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    level_zero = [candidate for candidate in corpus["candidates"] if candidate["dimension"] == 0]
    level_zero_ids = {candidate["candidate_id"] for candidate in level_zero}
    edges = [candidate for candidate in corpus["candidates"] if candidate["dimension"] == 1]
    targets_by_source: dict[str, set[str]] = {}
    for edge in edges:
        targets_by_source.setdefault(edge["source_id"], set()).add(edge["target_id"])
        assert edge["candidate_id"] == evaluation_runner._opaque_id(
            "candidate", edge["source_id"], edge["target_id"], edge["text"],
        )
        assert all(
            edge["candidate_id"] != evaluation_runner._opaque_id(
                "candidate", corpus["fixture_hash"], role,
                edge["source_id"], edge["target_id"],
            )
            for role in (0, 1)
        )
    assert set(targets_by_source) == level_zero_ids
    assert len(edges) == len(level_zero_ids) * (len(level_zero_ids) - 1)
    assert all(
        targets == level_zero_ids - {source_id}
        for source_id, targets in targets_by_source.items()
    )
    candidate_by_id = {candidate["candidate_id"]: candidate for candidate in level_zero}
    selected_variants: set[int] = set()
    selected_is_lexical_first: set[bool] = set()
    for gold in adjudication["ranking_cases"]:
        relevant_id = gold["relevant_ids"][0]
        relevant = candidate_by_id[relevant_id]
        indistinguishable = {
            candidate["candidate_id"] for candidate in level_zero
            if candidate["text"] == relevant["text"]
        }
        assert len(indistinguishable) == 2
        assert indistinguishable - {relevant_id}
        assert indistinguishable.isdisjoint(set(gold["negative_transfer_opportunities"]))
        case_id = gold["case_id"]
        variant_ids = [
            evaluation_runner._opaque_id("candidate", case_id, "neutral-variant", variant)
            for variant in range(2)
        ]
        selected_variants.add(variant_ids.index(relevant_id))
        selected_is_lexical_first.add(relevant_id == min(variant_ids))
    assert selected_variants == {0, 1}
    assert selected_is_lexical_first == {False, True}


def test_gold_only_fixture_mutation_preserves_blind_input_vectors_and_worker_output():
    """Rebuilding after a truth swap cannot change child-visible identity or ranking."""
    cohort = fixture_cohort("development")
    first = cohort.cases[0]
    swapped_case = replace(
        first,
        expected_boundary=not first.expected_boundary,
        expected_decisions=(not first.expected_decisions[0], *first.expected_decisions[1:]),
    )
    swapped = replace(cohort, cases=(swapped_case, *cohort.cases[1:]))
    assert fixture_hash(swapped) != fixture_hash(cohort)

    corpus, adjudication = evaluation_runner._build_blinded_inputs(cohort)
    swapped_corpus, swapped_adjudication = evaluation_runner._build_blinded_inputs(swapped)
    assert swapped_corpus == corpus
    assert evaluation_runner._canonical_hash(swapped_adjudication) != evaluation_runner._canonical_hash(adjudication)
    assert {
        candidate["candidate_id"]: evaluation_runner._fixture_vector(candidate["text"])
        for candidate in swapped_corpus["candidates"]
    } == {
        candidate["candidate_id"]: evaluation_runner._fixture_vector(candidate["text"])
        for candidate in corpus["candidates"]
    }

    output = evaluation_runner._run_blinded_ranking(corpus)
    swapped_output = evaluation_runner._run_blinded_ranking(swapped_corpus)
    stable_fields = (
        "baseline", "direct", "shadow", "shadow_direct",
        "compiler_cells", "compiler_direct_cells",
    )
    assert [
        {field: case[field] for field in stable_fields} for case in swapped_output["rankings"]
    ] == [
        {field: case[field] for field in stable_fields} for case in output["rankings"]
    ]
    predictions = evaluation_runner._predict_boundary_decisions(cohort, {
        "soft_threshold": 0.35, "hard_threshold": 0.65, "hard_confirmations": 2,
    })
    swapped_predictions = evaluation_runner._predict_boundary_decisions(swapped, {
        "soft_threshold": 0.35, "hard_threshold": 0.65, "hard_confirmations": 2,
    })
    assert swapped_predictions == predictions
    assert evaluation_runner._score_boundary_predictions(predictions, adjudication) != (
        evaluation_runner._score_boundary_predictions(swapped_predictions, swapped_adjudication)
    )


def test_ranking_truth_rebuild_preserves_blind_artifacts_and_changes_ranking_metrics():
    """Explicit relevance/context/transfer truth is parent-only across a full rebuild."""
    cohort = fixture_cohort("development")
    original_case = cohort.rankings[0]
    swapped_case = replace(
        original_case,
        relevant_variant=1 - original_case.relevant_variant,
        domain=f"{original_case.domain}-counterfactual",
        negative_transfer_truth=not original_case.negative_transfer_truth,
    )
    swapped = replace(cohort, rankings=(swapped_case, *cohort.rankings[1:]))
    corpus, adjudication = evaluation_runner._build_blinded_inputs(cohort)
    swapped_corpus, swapped_adjudication = evaluation_runner._build_blinded_inputs(swapped)
    assert swapped_corpus == corpus
    assert swapped_adjudication != adjudication
    assert swapped_adjudication["ranking_cases"][0] != adjudication["ranking_cases"][0]

    output = evaluation_runner._run_blinded_ranking(corpus)
    swapped_output = evaluation_runner._run_blinded_ranking(swapped_corpus)
    stable_fields = (
        "baseline", "direct", "shadow", "shadow_direct",
        "compiler_cells", "compiler_direct_cells",
    )
    assert [
        {field: case[field] for field in stable_fields} for case in swapped_output["rankings"]
    ] == [
        {field: case[field] for field in stable_fields} for case in output["rankings"]
    ]
    original_metrics = evaluation_runner._score_ranking_output(output, adjudication, corpus)
    swapped_metrics = evaluation_runner._score_ranking_output(
        swapped_output, swapped_adjudication, swapped_corpus,
    )
    assert swapped_metrics != original_metrics
    assert (
        swapped_metrics["baseline_mrr"],
        swapped_metrics["false_transfer_rate"],
    ) != (
        original_metrics["baseline_mrr"],
        original_metrics["false_transfer_rate"],
    )


def test_blind_worker_uses_separate_query_embeddings_and_survives_poisoned_gold_import(tmp_path):
    """The child needs only BlindCorpus and runs even when importing fixture gold is fatal."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "sitecustomize.py").write_text(
        "import importlib.abc, sys\n"
        "class BlockFixtures(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'experiments.category_evolution.fixtures':\n"
        "            raise RuntimeError('gold fixture import poisoned')\n"
        "        return None\n"
        "sys.meta_path.insert(0, BlockFixtures())\n"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(poison), str(Path(evaluation_runner.sqlite_vec.__file__).parent.parent),
        environment.get("PYTHONPATH"),
    )))
    environment["TMPDIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "experiments.category_evolution.runner", "--_ranking-worker"],
        input=json.dumps(corpus), capture_output=True, text=True, env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    evaluation_runner._validate_ranking_output(output, corpus)
    assert all(case["baseline"] != case["direct"] for case in output["rankings"])
    assert not list(tmp_path.glob("category-blind-ranking-*"))


def test_shadow_rankings_use_declared_baseline_universe_and_keep_full_compiler_evidence():
    """Scored baseline/shadow rows are comparable; full graph output remains auditable."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    corpus_cases = {case["case_id"]: case for case in corpus["cases"]}
    for ranking in output["rankings"]:
        eligible = set(corpus_cases[ranking["case_id"]]["candidate_ids"])
        for projected_name, full_name in (
            ("shadow", "compiler_cells"),
            ("shadow_direct", "compiler_direct_cells"),
        ):
            projected = ranking[projected_name]
            full = ranking[full_name]
            assert {row["candidate_id"] for row in projected} == eligible
            assert projected == [row for row in full if row["candidate_id"] in eligible]
            assert len(full) >= len(projected)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("hops", 5, "maximum hops"),
    ("token_count", 999_999, "token count"),
])
def test_ranking_output_rejects_row_probe_contradictions(field, value, message):
    """A child cannot hide an over-cap row behind a compliant summary probe."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    changed = copy.deepcopy(output)
    changed["rankings"][0]["compiler_cells"][0][field] = value
    with pytest.raises(ValueError, match=message):
        evaluation_runner._validate_ranking_output(changed, corpus)


def test_ranking_output_rejects_projection_and_distance_order_mutations():
    """Strict output validation reconciles child rankings to their source observations."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    changed_projection = copy.deepcopy(output)
    changed_projection["rankings"][0]["shadow"] = []
    with pytest.raises(ValueError, match="complete declared candidate universe"):
        evaluation_runner._validate_ranking_output(changed_projection, corpus)
    changed_distance = copy.deepcopy(output)
    changed_distance["rankings"][0]["baseline"].reverse()
    with pytest.raises(ValueError, match="distance order"):
        evaluation_runner._validate_ranking_output(changed_distance, corpus)


def test_ranking_output_rejects_reconciled_but_incomplete_shadow_universe():
    """Dropping an eligible candidate everywhere cannot suppress MRR/transfer evidence."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    changed = copy.deepcopy(output)
    case = changed["rankings"][0]
    removed_id = case["shadow"][-1]["candidate_id"]
    case["shadow"] = [row for row in case["shadow"] if row["candidate_id"] != removed_id]
    case["compiler_cells"] = [
        row for row in case["compiler_cells"] if row["candidate_id"] != removed_id
    ]
    probe = case["compiler"]["query"]
    probe["cell_count"] = len(case["compiler_cells"])
    probe["candidate_count"] = len(case["compiler_cells"])
    probe["token_count"] = sum(row["token_count"] for row in case["compiler_cells"])
    probe["max_hops"] = max(row["hops"] for row in case["compiler_cells"])
    raw, effective, hit = evaluation_runner._neighbor_observations(
        case["compiler_cells"], evaluation_runner._blind_adjacency(corpus),
    )
    probe["raw_max_neighbors"] = raw
    probe["max_neighbors_observed"] = effective
    probe["neighbor_limit_hit"] = hit
    with pytest.raises(ValueError, match="complete declared candidate universe"):
        evaluation_runner._validate_ranking_output(changed, corpus)


def test_adjudication_swap_changes_metrics_not_vectors_rankings_candidates_or_scores():
    """Gold is applied to an immutable completed worker result, never fed back into ranking."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    completed = json.dumps(output, sort_keys=True, separators=(",", ":"))
    vectors = {
        candidate["candidate_id"]: evaluation_runner._fixture_vector(candidate["text"])
        for candidate in corpus["candidates"] if candidate["dimension"] == 0
    }
    original = evaluation_runner._score_ranking_output(output, adjudication, corpus)
    changed = copy.deepcopy(adjudication)
    first_case = changed["ranking_cases"][0]
    original_relevant = first_case["relevant_ids"][0]
    original_label = first_case["candidate_context_labels"][original_relevant]
    ranked_ids = [row["candidate_id"] for row in output["rankings"][0]["baseline"]]
    replacement = next(
        identifier for identifier in ranked_ids
        if identifier != original_relevant
        and first_case["candidate_context_labels"][identifier] == original_label
    )
    first_case["relevant_ids"] = [replacement]
    rescored = evaluation_runner._score_ranking_output(output, changed, corpus)
    assert rescored != original
    assert json.dumps(output, sort_keys=True, separators=(",", ":")) == completed
    assert vectors == {
        candidate["candidate_id"]: evaluation_runner._fixture_vector(candidate["text"])
        for candidate in corpus["candidates"] if candidate["dimension"] == 0
    }


def test_adjudication_schema_and_fixture_mismatch_are_rejected():
    """Malformed or unrelated gold cannot be joined to a completed blind ranking."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    malformed = copy.deepcopy(adjudication)
    malformed["ranking_cases"][0]["negative_transfer_truth"] = {}
    with pytest.raises(ValueError, match="negative-transfer truth"):
        evaluation_runner._score_ranking_output(output, malformed, corpus)
    mismatch = copy.deepcopy(adjudication)
    mismatch["fixture_hash"] = "0" * 64
    with pytest.raises(ValueError, match="fixture hash"):
        evaluation_runner._score_ranking_output(output, mismatch, corpus)


def test_blind_fixture_hash_is_recomputed_from_the_child_visible_manifest():
    """A stale carried hash cannot join rankings for mutated observations to old gold."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    changed = copy.deepcopy(corpus)
    changed["cases"][0]["query_text"] = "unrelated mutated query"
    with pytest.raises(ValueError, match="fixture hash does not match"):
        evaluation_runner._validate_blind_corpus(changed)


def test_ranking_output_rejects_forged_neighbor_observations():
    """Raw/effective neighbor evidence is derived from graph rows, not trusted summaries."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    changed = copy.deepcopy(output)
    probe = changed["rankings"][0]["compiler"]["query"]
    assert probe["raw_max_neighbors"] > 0
    assert probe["max_neighbors_observed"] > 0
    probe["raw_max_neighbors"] = 0
    probe["max_neighbors_observed"] = 0
    probe["neighbor_limit_hit"] = False
    with pytest.raises(ValueError, match="neighbor observations"):
        evaluation_runner._validate_ranking_output(changed, corpus)


def test_json_schema_versions_and_fixed_integer_caps_reject_boolean_aliases():
    """JSON true must not satisfy an integer version or compiler-cap contract."""
    corpus, _adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    boolean_version = copy.deepcopy(corpus)
    boolean_version["schema_version"] = True
    with pytest.raises(ValueError, match="schema/version"):
        evaluation_runner._validate_blind_corpus(boolean_version)
    output = evaluation_runner._run_blinded_ranking(corpus)
    boolean_cap = copy.deepcopy(output)
    boolean_cap["compiler_limits"]["max_depth"] = True
    with pytest.raises(ValueError, match="five caps"):
        evaluation_runner._validate_ranking_output(boolean_cap, corpus)


def test_completed_ranking_mutation_changes_posthoc_metrics():
    """A real output-order mutation is observable by the parent scorer."""
    corpus, adjudication = evaluation_runner._build_blinded_inputs(fixture_cohort("development"))
    output = evaluation_runner._run_blinded_ranking(corpus)
    original = evaluation_runner._score_ranking_output(output, adjudication, corpus)
    changed = copy.deepcopy(output)
    relevant = adjudication["ranking_cases"][0]["relevant_ids"][0]
    ranking = changed["rankings"][0]["baseline"]
    relevant_index = next(index for index, row in enumerate(ranking) if row["candidate_id"] == relevant)
    other_index = 0 if relevant_index else 1
    ranking[relevant_index]["candidate_id"], ranking[other_index]["candidate_id"] = (
        ranking[other_index]["candidate_id"], ranking[relevant_index]["candidate_id"],
    )
    rescored = evaluation_runner._score_ranking_output(changed, adjudication, corpus)
    assert rescored["baseline_mrr"] != original["baseline_mrr"]


def test_ranking_worker_rejects_path_arguments(tmp_path):
    """The private ranking child accepts stdin JSON only, never a caller-selected database."""
    target = tmp_path / "attacker.db"
    completed = subprocess.run(
        [sys.executable, "-m", "experiments.category_evolution.runner",
         "--_ranking-worker", "--database", str(target)],
        input="{}", capture_output=True, text=True,
    )
    assert completed.returncode != 0
    assert not target.exists()
