"""Behavioral checks for the evolving-category acceptance harness."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from experiments.category_evolution.fixtures import fixture_cohort, fixture_hash
from experiments.category_evolution.metrics import (
    boundary_metrics,
    direct_recall_regression,
    false_transfer_rate,
    mean_reciprocal_rank,
    relative_mrr_improvement,
)
from experiments.category_evolution.runner import main as runner_main
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
    assert fixture_hash(development) == "25082a3cec57fe52e6ec6b277285a212936770eb149c077ecab2fbd7d1a21e27"
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
    assert completed.stdout.strip() == "25082a3cec57fe52e6ec6b277285a212936770eb149c077ecab2fbd7d1a21e27"


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
    assert report["ranking"]["direct_seed_source"] == "baseline_direct_top"
    assert report["ranking"]["cross_context_pairs"] == 4
    assert report["ranking"]["cross_context_candidates_evaluated"] >= 4
    assert len(report["ranking"]["compile_probes"]) == 8
    assert report["acceptance"]["gates"]["unexplained_replay_loss"]["passed"] is True
    assert report["configuration"]["shadow"] is True
    assert report["ranking_provenance"] == "controlled disposable fixture archive; not the supplied legacy archive"
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
