"""Run one disposable evolving-category evaluation and emit stable JSON."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import TYPE_CHECKING

import sqlite_vec

from categories import CategoryStore, EvolvingCategoryStore, WeightVector
from category_compile import CategoryCompiler, CompileBudget
from category_context import ContextObservation, ContextTracker
from category_evolution import import_legacy_category, legacy_proxy_id

from .benchmark import run_benchmark
from .metrics import (
    boundary_metrics,
    direct_recall_regression,
    false_transfer_rate,
    mean_reciprocal_rank,
    relative_mrr_improvement,
)

if TYPE_CHECKING:
    from .fixtures import FixtureCohort


DEFAULT_SEED = 20260807
BLIND_CORPUS_SCHEMA = "engram.category-evolution.blind-corpus"
ADJUDICATION_SCHEMA = "engram.category-evolution.adjudication"
RANKING_OUTPUT_SCHEMA = "engram.category-evolution.ranking-output"
BOUNDARY_INPUT_SCHEMA = "engram.category-evolution.boundary-input"
BOUNDARY_OUTPUT_SCHEMA = "engram.category-evolution.boundary-output"
SCHEMA_VERSION = 1
ENCODER_DIMENSIONS = 64
ENCODER_SEED = "category-eval-v1:"
ENCODER_SPEC = {
    "version": "sha256-signed-feature-hash-v1",
    "seed": ENCODER_SEED,
    "dimensions": ENCODER_DIMENSIONS,
    "features": ["normalized_tokens", "adjacent_bigrams"],
    "hash": "sha256",
    "signed": True,
    "l2_normalized": True,
}
_RANKING_WORKER_FLAG = "--_ranking-worker"
_BOUNDARY_WORKER_FLAG = "--_boundary-worker"
_COMPILER_CAPS = {
    "max_depth": 4,
    "max_neighbors": 64,
    "max_candidates": 50_000,
    "wall_time_ms": 500,
    "hard_ceiling": 65_536,
}
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
_PREQUERY_OBSERVED_AT = "2026-08-06T00:00:00+00:00"
_HISTORY_WEIGHT_PROFILES = (
    {
        "relevance": 0.90, "evidence": 0.80, "recency": 0.70,
        "affect": 0.0, "adoption": 0.50, "novelty": 0.20, "cost": 0.10,
    },
    {
        "relevance": 0.20, "evidence": 0.60, "recency": 0.40,
        "affect": 0.0, "adoption": 0.20, "novelty": 0.20, "cost": 0.10,
    },
)


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
    parser.add_argument("--benchmark-cells", type=int,
                        help="run the benchmark now; only 1000000 is acceptance evidence")
    return parser


def run_evaluation(args: argparse.Namespace) -> dict[str, object]:
    """Rank blind data in a child, validate it, then apply parent-only gold."""
    from .fixtures import fixture_cohort, fixture_hash

    _validate_args(args)
    cohort = fixture_cohort(args.cohort, seed=args.seed)
    expected_fixture_hash = fixture_hash(cohort)
    blind_corpus, adjudication = _build_blinded_inputs(cohort)
    ranking_output = _run_blinded_ranking(blind_corpus)
    ranking = _score_ranking_output(ranking_output, adjudication, blind_corpus)
    boundary_output = _run_blinded_boundaries(blind_corpus, _configuration(args))
    boundary = _score_boundary_predictions(boundary_output["predictions"], adjudication)
    legacy = _find_legacy(args.legacy)
    resource_benchmark = _run_requested_benchmark(args)
    compiler_probes = list(ranking["compile_probes"])
    if isinstance(resource_benchmark, dict) and isinstance(resource_benchmark.get("compiler"), dict):
        compiler_probes.append(resource_benchmark["compiler"])
    report: dict[str, object] = {
        "schema_version": 2,
        "cohort": cohort.name,
        "seed": cohort.seed,
        "fixture_hash": expected_fixture_hash,
        "fixture_cases": len(cohort.cases),
        "configuration": _configuration(args),
        "boundary_metrics": boundary,
        "ranking": ranking,
        "ranking_output": ranking_output,
        "ranking_blinded": True,
        "blind_corpus": {
            "schema": BLIND_CORPUS_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "hash": _canonical_hash(blind_corpus),
        },
        "adjudication": {
            "schema": ADJUDICATION_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "hash": _canonical_hash(adjudication),
        },
        "compiler_limits": ranking_output["compiler_limits"],
        "import_report": None,
        "import_reports": [],
        "replay_hashes": [],
        "replay_digests": [],
        "replay_identical": False,
        "compiler_probe": None,
        "compiler_probes": compiler_probes,
        "environmental_limitation": None,
        "resource_benchmark": resource_benchmark,
        "ranking_provenance": "validated blind subprocess over a controlled disposable fixture archive",
        "replay_provenance": "supplied/discovered legacy archive is replayed independently",
    }
    if legacy is None:
        report["environmental_limitation"] = (
            "legacy categories.db was not found; legacy replay and its compiler probe were not run"
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
    report["compiler_probes"] = [compiler_probe, *compiler_probes]
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
        return explicit.resolve() if explicit.exists() else None
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


def _opaque_id(namespace: str, *parts: object) -> str:
    payload = "\x1f".join((namespace, *(str(part) for part in parts)))
    return f"{namespace}-{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def _blind_manifest_hash(corpus: Mapping[str, object]) -> str:
    """Bind a BlindCorpus identity to every child-visible manifest field."""
    return _canonical_hash({
        key: corpus[key] for key in (
            "schema", "schema_version", "encoder", "cases", "boundary_cases",
            "candidates",
        )
    })


def _build_blinded_inputs(cohort: FixtureCohort) -> tuple[dict[str, object], dict[str, object]]:
    """Split one fixture into non-gold child input and parent-only adjudication."""
    candidates: dict[str, dict[str, object]] = {}
    candidate_contexts: dict[str, str] = {}
    cases: list[dict[str, object]] = []
    private_cases: list[dict[str, object]] = []
    for case in cohort.rankings:
        if (
            case.relevant_variant not in (0, 1)
            or case.history_preferred_variant not in (0, 1)
            or type(case.negative_transfer_truth) is not bool
        ):
            raise ValueError("ranking fixture truth is invalid")
        case_id = _opaque_id("case", case.query, case.direct_query)
        context_label = _opaque_id("gold-context", case.domain)
        neutral_text = f"{case.query} {case.direct_query} memory"
        neutral_ids = tuple(
            _opaque_id("candidate", case_id, "neutral-variant", variant)
            for variant in range(2)
        )
        for candidate_id in neutral_ids:
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "text": neutral_text,
                "dimension": 0,
                "source_id": None,
                "target_id": None,
            }
            candidate_contexts[candidate_id] = context_label
        history_observations = []
        for variant, candidate_id in enumerate(neutral_ids):
            profile = _HISTORY_WEIGHT_PROFILES[
                0 if variant == case.history_preferred_variant else 1
            ]
            history_observations.append({
                "candidate_id": candidate_id,
                "observed_at": _PREQUERY_OBSERVED_AT,
                "weights": dict(profile),
            })
        cases.append({
            "case_id": case_id,
            "query_text": case.query,
            "direct_query_text": case.direct_query,
            "candidate_ids": [],
            "seed_candidate_ids": list(neutral_ids),
            "context_features": {
                _opaque_id("context-feature", case_id): 1.0,
            },
            "history_observations": history_observations,
        })
        private_cases.append({
            "case_id": case_id,
            "context_label": context_label,
            "candidate_ids": neutral_ids,
            "relevant_id": neutral_ids[case.relevant_variant],
            "negative_transfer_truth": case.negative_transfer_truth,
        })

    level_zero_ids = sorted(candidates)
    # The complete directed graph is invariant under any level-zero candidate
    # permutation: every candidate appears equally as source and target.
    for source_id in level_zero_ids:
        for target_id in level_zero_ids:
            if source_id == target_id:
                continue
            edge_id = _opaque_id(
                "candidate", source_id, target_id, "structural association",
            )
            candidates[edge_id] = {
                "candidate_id": edge_id,
                "text": "structural association",
                "dimension": 1,
                "source_id": source_id,
                "target_id": target_id,
            }

    for case in cases:
        case["candidate_ids"] = list(level_zero_ids)

    ranking_adjudication = []
    for private in private_cases:
        relevant_id = str(private["relevant_id"])
        local_ids = set(str(identifier) for identifier in private["candidate_ids"])
        foreign_ids = sorted(
            str(other["relevant_id"]) for other in private_cases
            if str(other["relevant_id"]) not in local_ids
        )
        ranking_adjudication.append({
            "case_id": private["case_id"],
            "relevant_ids": [relevant_id],
            "candidate_context_labels": {
                identifier: candidate_contexts[identifier] for identifier in level_zero_ids
            },
            "negative_transfer_opportunities": foreign_ids,
            "negative_transfer_truth": {
                foreign_id: bool(private["negative_transfer_truth"])
                for foreign_id in foreign_ids
            },
        })

    blind_boundary_cases: list[dict[str, object]] = []
    boundary_adjudication: list[dict[str, object]] = []
    for index, case in enumerate(cohort.cases):
        observations = [_blind_observation(observation) for observation in case.observations]
        case_id = _opaque_id(
            "boundary-case", index, _canonical_hash(observations)
        )
        blind_boundary_cases.append({
            "case_id": case_id,
            "observations": observations,
        })
        boundary_adjudication.append({
            "case_id": case_id,
            "kind": case.kind,
            "expected_decisions": list(case.expected_decisions),
        })

    blind_corpus: dict[str, object] = {
        "schema": BLIND_CORPUS_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "encoder": dict(ENCODER_SPEC),
        "cases": cases,
        "boundary_cases": blind_boundary_cases,
        "candidates": sorted(
            candidates.values(),
            key=lambda item: (int(item["dimension"]), str(item["candidate_id"])),
        ),
    }
    blind_fixture_hash = _blind_manifest_hash(blind_corpus)
    blind_corpus["fixture_hash"] = blind_fixture_hash
    adjudication: dict[str, object] = {
        "schema": ADJUDICATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "fixture_hash": blind_fixture_hash,
        "ranking_cases": ranking_adjudication,
        "boundary_cases": boundary_adjudication,
    }
    _validate_blind_corpus(blind_corpus)
    _validate_adjudication(adjudication, blind_corpus)
    return blind_corpus, adjudication


def _blind_observation(observation: ContextObservation) -> dict[str, object]:
    """Serialize only generic, predictor-visible boundary evidence."""
    return {
        "goal": dict(observation.goal),
        "entities": dict(observation.entities),
        "participants": dict(observation.participants),
        "tools": dict(observation.tools),
        "sources": dict(observation.sources),
        "attention": dict(observation.attention),
        "observed_at": observation.observed_at.isoformat(),
        "explicit_boundary": observation.explicit_boundary,
    }


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if set(value) != expected:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _valid_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _validate_encoder(value: object, label: str) -> None:
    encoder = _require_exact_keys(value, {
        "version", "seed", "dimensions", "features", "hash", "signed", "l2_normalized",
    }, label)
    if (
        encoder != ENCODER_SPEC
        or type(encoder["dimensions"]) is not int
        or type(encoder["signed"]) is not bool
        or type(encoder["l2_normalized"]) is not bool
        or not isinstance(encoder["features"], list)
    ):
        raise ValueError(f"{label} contract is invalid")


def _validate_blind_corpus(corpus: object) -> dict[str, object]:
    corpus = _require_exact_keys(corpus, {
        "schema", "schema_version", "fixture_hash", "encoder", "cases",
        "boundary_cases", "candidates",
    }, "BlindCorpus")
    if (
        corpus["schema"] != BLIND_CORPUS_SCHEMA
        or type(corpus["schema_version"]) is not int
        or corpus["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("BlindCorpus schema/version is unsupported")
    if not _valid_hash(corpus["fixture_hash"]):
        raise ValueError("BlindCorpus fixture hash is invalid")
    _validate_encoder(corpus["encoder"], "BlindCorpus encoder")
    candidates = corpus["candidates"]
    cases = corpus["cases"]
    if not isinstance(candidates, list) or not candidates or not isinstance(cases, list) or not cases:
        raise ValueError("BlindCorpus cases and candidates must be non-empty arrays")
    candidate_map: dict[str, dict[str, object]] = {}
    for raw_candidate in candidates:
        candidate = _require_exact_keys(raw_candidate, {
            "candidate_id", "text", "dimension", "source_id", "target_id",
        }, "BlindCorpus candidate")
        candidate_id = candidate["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in candidate_map:
            raise ValueError("BlindCorpus candidate IDs must be unique non-empty strings")
        if not isinstance(candidate["text"], str) or not candidate["text"]:
            raise ValueError("BlindCorpus candidate text must be non-empty")
        if type(candidate["dimension"]) is not int or int(candidate["dimension"]) < 0:
            raise ValueError("BlindCorpus candidate dimension must be non-negative")
        candidate_map[candidate_id] = candidate
    for candidate_id, candidate in candidate_map.items():
        dimension = int(candidate["dimension"])
        source_id, target_id = candidate["source_id"], candidate["target_id"]
        if dimension == 0:
            if source_id is not None or target_id is not None:
                raise ValueError("BlindCorpus dimension-zero candidates cannot have graph boundaries")
        elif (
            not isinstance(source_id, str) or not isinstance(target_id, str)
            or source_id not in candidate_map or target_id not in candidate_map
            or int(candidate_map[source_id]["dimension"]) >= dimension
            or int(candidate_map[target_id]["dimension"]) >= dimension
        ):
            raise ValueError(f"BlindCorpus candidate {candidate_id} has invalid graph data")
    level_zero_ids = {
        identifier for identifier, candidate in candidate_map.items()
        if candidate["dimension"] == 0
    }
    case_ids: set[str] = set()
    for raw_case in cases:
        case = _require_exact_keys(raw_case, {
            "case_id", "query_text", "direct_query_text", "candidate_ids",
            "seed_candidate_ids", "context_features", "history_observations",
        }, "BlindCorpus case")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("BlindCorpus case IDs must be unique non-empty strings")
        case_ids.add(case_id)
        if not isinstance(case["query_text"], str) or not case["query_text"]:
            raise ValueError("BlindCorpus query text must be non-empty")
        if not isinstance(case["direct_query_text"], str) or not case["direct_query_text"]:
            raise ValueError("BlindCorpus direct-query text must be non-empty")
        candidate_ids = case["candidate_ids"]
        if (
            not isinstance(candidate_ids, list)
            or any(not isinstance(identifier, str) for identifier in candidate_ids)
            or len(set(candidate_ids)) != len(candidate_ids)
            or set(candidate_ids) != level_zero_ids
        ):
            raise ValueError("BlindCorpus case candidate IDs must name the complete level-zero corpus")
        seeds = case["seed_candidate_ids"]
        context_features = case["context_features"]
        history = case["history_observations"]
        if (
            not isinstance(seeds, list)
            or len(seeds) != 2
            or any(not isinstance(identifier, str) for identifier in seeds)
            or len(set(seeds)) != len(seeds)
            or not set(seeds) <= level_zero_ids
        ):
            raise ValueError("BlindCorpus history seeds must name two distinct candidates")
        if (
            not isinstance(context_features, dict)
            or not context_features
            or any(
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                for key, value in context_features.items()
            )
        ):
            raise ValueError("BlindCorpus context features are invalid")
        if not isinstance(history, list) or len(history) != len(seeds):
            raise ValueError("BlindCorpus pre-query history is incomplete")
        history_ids: set[str] = set()
        for raw_observation in history:
            observation = _require_exact_keys(
                raw_observation,
                {"candidate_id", "observed_at", "weights"},
                "BlindCorpus history observation",
            )
            candidate_id = observation["candidate_id"]
            if (
                not isinstance(candidate_id, str)
                or candidate_id not in seeds
                or candidate_id in history_ids
            ):
                raise ValueError("BlindCorpus history candidate IDs are invalid")
            history_ids.add(candidate_id)
            observed_at = observation["observed_at"]
            if not isinstance(observed_at, str):
                raise ValueError("BlindCorpus history timestamp must be text")
            try:
                timestamp = datetime.fromisoformat(observed_at)
            except ValueError as exc:
                raise ValueError("BlindCorpus history timestamp is invalid") from exc
            cutoff = datetime.fromisoformat(_PREQUERY_OBSERVED_AT)
            if (
                timestamp.tzinfo is None
                or timestamp.utcoffset() is None
                or timestamp > cutoff
            ):
                raise ValueError("BlindCorpus history must predate evaluation queries")
            weights = _require_exact_keys(
                observation["weights"],
                {
                    "relevance", "evidence", "recency", "affect",
                    "adoption", "novelty", "cost",
                },
                "BlindCorpus history weights",
            )
            try:
                WeightVector(**weights)
            except (TypeError, ValueError) as exc:
                raise ValueError("BlindCorpus history weights are invalid") from exc
        if history_ids != set(seeds):
            raise ValueError("BlindCorpus history does not cover its seeds")
    boundary_cases = corpus["boundary_cases"]
    if not isinstance(boundary_cases, list) or not boundary_cases:
        raise ValueError("BlindCorpus boundary cases must be a non-empty array")
    boundary_ids: set[str] = set()
    observation_fields = {
        "goal", "entities", "participants", "tools", "sources", "attention",
        "observed_at", "explicit_boundary",
    }
    for raw_case in boundary_cases:
        case = _require_exact_keys(
            raw_case, {"case_id", "observations"}, "BlindCorpus boundary case"
        )
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in boundary_ids:
            raise ValueError("BlindCorpus boundary case IDs must be unique")
        boundary_ids.add(case_id)
        observations = case["observations"]
        if not isinstance(observations, list) or not observations:
            raise ValueError("BlindCorpus boundary observations must be non-empty")
        for raw_observation in observations:
            observation = _require_exact_keys(
                raw_observation, observation_fields, "BlindCorpus boundary observation"
            )
            for field in ("goal", "entities", "participants", "tools", "sources", "attention"):
                values = observation[field]
                if not isinstance(values, dict) or any(
                    not isinstance(key, str)
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < 0
                    for key, value in values.items()
                ):
                    raise ValueError("BlindCorpus boundary feature maps are invalid")
            if type(observation["explicit_boundary"]) is not bool:
                raise ValueError("BlindCorpus explicit boundary flag must be bool")
            if not isinstance(observation["observed_at"], str):
                raise ValueError("BlindCorpus boundary timestamp must be text")
            try:
                observed_at = datetime.fromisoformat(observation["observed_at"])
            except ValueError as exc:
                raise ValueError("BlindCorpus boundary timestamp is invalid") from exc
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError("BlindCorpus boundary timestamp must be timezone-aware")
    if corpus["fixture_hash"] != _blind_manifest_hash(corpus):
        raise ValueError("BlindCorpus fixture hash does not match its visible manifest")
    return corpus


def _validate_adjudication(adjudication: object, corpus: object) -> dict[str, object]:
    corpus = _validate_blind_corpus(corpus)
    adjudication = _require_exact_keys(adjudication, {
        "schema", "schema_version", "fixture_hash", "ranking_cases", "boundary_cases",
    }, "Adjudication")
    if (
        adjudication["schema"] != ADJUDICATION_SCHEMA
        or type(adjudication["schema_version"]) is not int
        or adjudication["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("Adjudication schema/version is unsupported")
    if adjudication["fixture_hash"] != corpus["fixture_hash"]:
        raise ValueError("Adjudication fixture hash does not match BlindCorpus fixture hash")
    corpus_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    ranking_cases = adjudication["ranking_cases"]
    if not isinstance(ranking_cases, list) or len(ranking_cases) != len(corpus_cases):
        raise ValueError("Adjudication ranking cases do not match BlindCorpus")
    seen: set[str] = set()
    for raw_case in ranking_cases:
        case = _require_exact_keys(raw_case, {
            "case_id", "relevant_ids", "candidate_context_labels",
            "negative_transfer_opportunities", "negative_transfer_truth",
        }, "Adjudication ranking case")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or case_id not in corpus_cases or case_id in seen:
            raise ValueError("Adjudication case IDs do not match BlindCorpus")
        seen.add(case_id)
        allowed = set(corpus_cases[case_id]["candidate_ids"])
        relevant = case["relevant_ids"]
        if (
            not isinstance(relevant, list) or not relevant
            or any(not isinstance(item, str) for item in relevant)
            or len(set(relevant)) != len(relevant) or not set(relevant) <= allowed
        ):
            raise ValueError("Adjudication relevant IDs are invalid")
        labels = case["candidate_context_labels"]
        if (
            not isinstance(labels, dict) or set(labels) != allowed
            or any(not isinstance(value, str) or not value for value in labels.values())
        ):
            raise ValueError("Adjudication candidate context labels are invalid")
        opportunities = case["negative_transfer_opportunities"]
        truth = case["negative_transfer_truth"]
        if (
            not isinstance(opportunities, list)
            or any(not isinstance(item, str) for item in opportunities)
            or len(set(opportunities)) != len(opportunities)
            or not set(opportunities) <= allowed
            or not isinstance(truth, dict)
            or set(truth) != set(opportunities)
            or any(type(value) is not bool for value in truth.values())
        ):
            raise ValueError("Adjudication negative-transfer truth does not match its opportunities")
    if seen != set(corpus_cases):
        raise ValueError("Adjudication ranking cases do not cover BlindCorpus")
    boundary_cases = adjudication["boundary_cases"]
    if not isinstance(boundary_cases, list):
        raise ValueError("Adjudication boundary cases must be an array")
    corpus_boundary_ids = {
        str(case["case_id"]) for case in corpus["boundary_cases"]
    }
    boundary_ids: set[str] = set()
    for raw_case in boundary_cases:
        case = _require_exact_keys(raw_case, {"case_id", "kind", "expected_decisions"},
                                   "Adjudication boundary case")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in boundary_ids:
            raise ValueError("Adjudication boundary case IDs must be unique")
        boundary_ids.add(case_id)
        if case["kind"] not in {"explicit", "abrupt", "gradual"}:
            raise ValueError("Adjudication boundary kind is invalid")
        decisions = case["expected_decisions"]
        if not isinstance(decisions, list) or not decisions or any(type(item) is not bool for item in decisions):
            raise ValueError("Adjudication expected boundary decisions are invalid")
        corpus_case = next(
            item for item in corpus["boundary_cases"] if item["case_id"] == case_id
        ) if case_id in corpus_boundary_ids else None
        if corpus_case is None or len(decisions) != len(corpus_case["observations"]):
            raise ValueError("Adjudication boundary cases do not match BlindCorpus")
    if boundary_ids != corpus_boundary_ids:
        raise ValueError("Adjudication boundary cases do not cover BlindCorpus")
    return adjudication


def _run_blinded_ranking(corpus: object) -> dict[str, object]:
    """Pass only canonical BlindCorpus JSON to a fresh worker process."""
    validated = _validate_blind_corpus(corpus)
    completed = subprocess.run(
        [sys.executable, "-m", "experiments.category_evolution.runner", _RANKING_WORKER_FLAG],
        input=_canonical_json(validated),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "blind ranking worker failed")
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("blind ranking worker emitted malformed JSON") from exc
    return _validate_ranking_output(output, validated)


def _boundary_worker_input(
    corpus: object, configuration: Mapping[str, object]
) -> dict[str, object]:
    """Build the complete, gold-free stdin contract for boundary inference."""
    validated = _validate_blind_corpus(corpus)
    selected = {
        name: configuration[name]
        for name in ("soft_threshold", "hard_threshold", "hard_confirmations")
    }
    _validate_boundary_configuration(selected)
    return {
        "schema": BOUNDARY_INPUT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "fixture_hash": validated["fixture_hash"],
        "configuration": selected,
        "cases": validated["boundary_cases"],
    }


def _validate_boundary_configuration(configuration: object) -> dict[str, object]:
    configuration = _require_exact_keys(
        configuration,
        {"soft_threshold", "hard_threshold", "hard_confirmations"},
        "BoundaryInput configuration",
    )
    ContextTracker(
        soft_threshold=configuration["soft_threshold"],
        hard_threshold=configuration["hard_threshold"],
        hard_confirmations=configuration["hard_confirmations"],
    )
    return configuration


def _validate_boundary_input(worker_input: object) -> dict[str, object]:
    worker_input = _require_exact_keys(
        worker_input,
        {"schema", "schema_version", "fixture_hash", "configuration", "cases"},
        "BoundaryInput",
    )
    if (
        worker_input["schema"] != BOUNDARY_INPUT_SCHEMA
        or type(worker_input["schema_version"]) is not int
        or worker_input["schema_version"] != SCHEMA_VERSION
        or not _valid_hash(worker_input["fixture_hash"])
    ):
        raise ValueError("BoundaryInput schema/version is unsupported")
    _validate_boundary_configuration(worker_input["configuration"])
    cases = worker_input["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("BoundaryInput cases must be a non-empty array")
    case_ids: set[str] = set()
    for raw_case in cases:
        case = _require_exact_keys(
            raw_case, {"case_id", "observations"}, "BoundaryInput case"
        )
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError("BoundaryInput case IDs must be unique")
        case_ids.add(case_id)
        if not isinstance(case["observations"], list) or not case["observations"]:
            raise ValueError("BoundaryInput observations must be non-empty")
        for raw_observation in case["observations"]:
            observation = _require_exact_keys(
                raw_observation,
                {
                    "goal", "entities", "participants", "tools", "sources",
                    "attention", "observed_at", "explicit_boundary",
                },
                "BoundaryInput observation",
            )
            try:
                ContextObservation(
                    goal=observation["goal"],
                    entities=observation["entities"],
                    participants=observation["participants"],
                    tools=observation["tools"],
                    sources=observation["sources"],
                    attention=observation["attention"],
                    observed_at=datetime.fromisoformat(observation["observed_at"]),
                    explicit_boundary=observation["explicit_boundary"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("BoundaryInput observation is invalid") from exc
    return worker_input


def _run_blinded_boundaries(
    corpus: object, configuration: Mapping[str, object]
) -> dict[str, object]:
    """Predict boundaries in a fresh interpreter that never imports fixture gold."""
    worker_input = _boundary_worker_input(corpus, configuration)
    completed = subprocess.run(
        [sys.executable, "-m", "experiments.category_evolution.runner", _BOUNDARY_WORKER_FLAG],
        input=_canonical_json(worker_input),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "blind boundary worker failed")
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("blind boundary worker emitted malformed JSON") from exc
    return _validate_boundary_output(output, worker_input)


def _boundary_worker_main() -> int:
    try:
        worker_input = _validate_boundary_input(json.loads(sys.stdin.read()))
        output = _execute_blind_boundaries(worker_input)
    except (json.JSONDecodeError, RuntimeError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(output))
    return 0


def _execute_blind_boundaries(worker_input: dict[str, object]) -> dict[str, object]:
    configuration = worker_input["configuration"]
    predictions: list[dict[str, object]] = []
    for case in worker_input["cases"]:
        tracker = ContextTracker(
            soft_threshold=configuration["soft_threshold"],
            hard_threshold=configuration["hard_threshold"],
            hard_confirmations=configuration["hard_confirmations"],
        )
        decisions: list[bool] = []
        for raw in case["observations"]:
            observation = ContextObservation(
                goal=raw["goal"],
                entities=raw["entities"],
                participants=raw["participants"],
                tools=raw["tools"],
                sources=raw["sources"],
                attention=raw["attention"],
                observed_at=datetime.fromisoformat(raw["observed_at"]),
                explicit_boundary=raw["explicit_boundary"],
            )
            decisions.append(tracker.observe(observation).kind == "hard")
        predictions.append({"case_id": case["case_id"], "decisions": decisions})
    return {
        "schema": BOUNDARY_OUTPUT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "fixture_hash": worker_input["fixture_hash"],
        "input_hash": _canonical_hash(worker_input),
        "predictions": predictions,
    }


def _validate_boundary_output(output: object, worker_input: object) -> dict[str, object]:
    worker_input = _validate_boundary_input(worker_input)
    output = _require_exact_keys(
        output,
        {"schema", "schema_version", "fixture_hash", "input_hash", "predictions"},
        "BoundaryOutput",
    )
    if (
        output["schema"] != BOUNDARY_OUTPUT_SCHEMA
        or type(output["schema_version"]) is not int
        or output["schema_version"] != SCHEMA_VERSION
        or output["fixture_hash"] != worker_input["fixture_hash"]
        or output["input_hash"] != _canonical_hash(worker_input)
    ):
        raise ValueError("BoundaryOutput identity does not match BoundaryInput")
    expected = {
        str(case["case_id"]): len(case["observations"])
        for case in worker_input["cases"]
    }
    predictions = output["predictions"]
    if not isinstance(predictions, list) or len(predictions) != len(expected):
        raise ValueError("BoundaryOutput predictions are incomplete")
    seen: set[str] = set()
    for raw_prediction in predictions:
        prediction = _require_exact_keys(
            raw_prediction, {"case_id", "decisions"}, "BoundaryOutput prediction"
        )
        case_id = prediction["case_id"]
        decisions = prediction["decisions"]
        if (
            not isinstance(case_id, str)
            or case_id not in expected
            or case_id in seen
            or not isinstance(decisions, list)
            or len(decisions) != expected[case_id]
            or any(type(decision) is not bool for decision in decisions)
        ):
            raise ValueError("BoundaryOutput predictions do not match BoundaryInput")
        seen.add(case_id)
    if seen != set(expected):
        raise ValueError("BoundaryOutput predictions do not cover BoundaryInput")
    return output


def _ranking_worker_main() -> int:
    try:
        corpus = json.loads(sys.stdin.read())
        output = _execute_blind_ranking(_validate_blind_corpus(corpus))
    except (json.JSONDecodeError, OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(output))
    return 0


def _execute_blind_ranking(corpus: dict[str, object]) -> dict[str, object]:
    """Worker-only controlled retrieval/replay/compiler path; no fixture import."""
    temporary = Path(tempfile.mkdtemp(prefix="category-blind-ranking-"))
    try:
        legacy = temporary / "current_categories.db"
        shadow = temporary / "shadow_categories_v2.db"
        baselines = _build_current_blind_archive(legacy, corpus)
        imported = import_legacy_category(legacy, shadow)
        rankings = _compile_blind_rankings(shadow, imported.root_epoch_id, corpus, baselines)
        output: dict[str, object] = {
            "schema": RANKING_OUTPUT_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "fixture_hash": corpus["fixture_hash"],
            "corpus_hash": _canonical_hash(corpus),
            "encoder": dict(ENCODER_SPEC),
            "baseline_source": "CategoryStore.search",
            "compiler_limits": dict(_COMPILER_CAPS),
            "fixture_import": asdict(imported),
            "rankings": rankings,
        }
        return _validate_ranking_output(output, corpus)
    finally:
        shutil.rmtree(temporary)


def _build_current_blind_archive(database: Path, corpus: dict[str, object]) -> dict[str, dict[str, list[dict[str, object]]]]:
    connection = sqlite3.connect(database)
    _load_vec(connection)
    current = CategoryStore(connection, dimension=ENCODER_DIMENSIONS)
    try:
        candidates = sorted(corpus["candidates"], key=lambda item: (int(item["dimension"]), str(item["candidate_id"])))
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            if candidate["dimension"] == 0:
                generated = current.add_cell(
                    str(candidate["text"]),
                    context={"evaluation": "blind-ranking"},
                    embedding=_fixture_vector(str(candidate["text"])),
                )
            else:
                generated = current.compose(
                    str(candidate["source_id"]), str(candidate["target_id"]),
                    str(candidate["text"]), context={"evaluation": "blind-ranking"},
                )
            connection.execute("UPDATE cells SET id = ? WHERE id = ?", (candidate_id, generated))
            connection.commit()
        results: dict[str, dict[str, list[dict[str, object]]]] = {}
        for case in corpus["cases"]:
            limit = len(case["candidate_ids"])
            query_rows = current.search(_fixture_vector(str(case["query_text"])), level=0, limit=limit)
            direct_rows = current.search(_fixture_vector(str(case["direct_query_text"])), level=0, limit=limit)
            results[str(case["case_id"])] = {
                "baseline": [
                    {"candidate_id": str(row["id"]), "distance": float(row["distance"])}
                    for row in query_rows
                ],
                "direct": [
                    {"candidate_id": str(row["id"]), "distance": float(row["distance"])}
                    for row in direct_rows
                ],
            }
        return results
    finally:
        connection.close()


def _compile_blind_rankings(
    database: Path,
    epoch_id: str,
    corpus: dict[str, object],
    baselines: Mapping[str, Mapping[str, list[dict[str, object]]]],
) -> list[dict[str, object]]:
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    compiler = CategoryCompiler(store, CompileBudget())
    proxy_to_opaque: dict[str, str] = {}
    for candidate in corpus["candidates"]:
        candidate_id = str(candidate["candidate_id"])
        # Replay preserves higher-cell IDs but translates legacy graph
        # endpoints into stable memory proxies.  Both identities are derived
        # solely from the opaque corpus ID, never from adjudication.
        proxy_to_opaque[candidate_id] = candidate_id
        if int(candidate["dimension"]) == 0:
            proxy_to_opaque[legacy_proxy_id(candidate_id)] = candidate_id
    adjacency = _blind_adjacency(corpus)
    try:
        results: list[dict[str, object]] = []
        for case in corpus["cases"]:
            case_id = str(case["case_id"])
            baseline = baselines[case_id]
            if not baseline["baseline"] or not baseline["direct"]:
                raise RuntimeError("CategoryStore.search returned incomplete blind rankings")
            context_id = store.create_context(
                case["context_features"],
                context_id=_opaque_id("worker-context", case_id),
            )
            for observation in case["history_observations"]:
                candidate_id = str(observation["candidate_id"])
                evidence_event_id = store.append_event(
                    "evaluation_history_observation",
                    {
                        "case_id": case_id,
                        "candidate_id": candidate_id,
                        "context_features": case["context_features"],
                        "observed_at": observation["observed_at"],
                    },
                )
                store.observe_weight(
                    legacy_proxy_id(candidate_id),
                    context_id,
                    WeightVector(**observation["weights"]),
                    evidence_event_id=evidence_event_id,
                )
            seed_ids = tuple(
                legacy_proxy_id(str(candidate_id))
                for candidate_id in case["seed_candidate_ids"]
            )
            compiler_cells, query_probe = _timed_blind_compile(
                compiler, epoch_id, context_id,
                seed_ids,
                "query", proxy_to_opaque, adjacency,
            )
            compiler_direct_cells, direct_probe = _timed_blind_compile(
                compiler, epoch_id, context_id,
                seed_ids,
                "direct", proxy_to_opaque, adjacency,
            )
            eligible = set(str(identifier) for identifier in case["candidate_ids"])
            shadow = [row for row in compiler_cells if row["candidate_id"] in eligible]
            shadow_direct = [
                row for row in compiler_direct_cells if row["candidate_id"] in eligible
            ]
            results.append({
                "case_id": case_id,
                "baseline": baseline["baseline"],
                "direct": baseline["direct"],
                "shadow": shadow,
                "shadow_direct": shadow_direct,
                "compiler_cells": compiler_cells,
                "compiler_direct_cells": compiler_direct_cells,
                "compiler": {"query": query_probe, "direct": direct_probe},
            })
        return results
    finally:
        compiler.close()
        store.close()


def _blind_adjacency(corpus: Mapping[str, object]) -> dict[str, set[str]]:
    candidates = corpus["candidates"]
    assert isinstance(candidates, list)
    adjacency: dict[str, set[str]] = {
        str(candidate["candidate_id"]): set() for candidate in candidates
    }
    for candidate in candidates:
        if int(candidate["dimension"]) > 0:
            edge_id = str(candidate["candidate_id"])
            source_id = str(candidate["source_id"])
            target_id = str(candidate["target_id"])
            adjacency[edge_id].update((source_id, target_id))
            adjacency[source_id].add(edge_id)
            adjacency[target_id].add(edge_id)
    return adjacency


def _neighbor_observations(
    rows: Sequence[Mapping[str, object]],
    adjacency: Mapping[str, set[str]],
) -> tuple[int, int, bool]:
    compiled_ids = {str(row["candidate_id"]) for row in rows}
    expanded_ids = {
        str(row["candidate_id"]) for row in rows
        if int(row["hops"]) < _COMPILER_CAPS["max_depth"]
    }
    raw_max_neighbors = max(
        (len(adjacency.get(identifier, ())) for identifier in expanded_ids),
        default=0,
    )
    max_neighbors_observed = max(
        (len(set(adjacency.get(identifier, ())) & compiled_ids) for identifier in expanded_ids),
        default=0,
    )
    return (
        raw_max_neighbors,
        max_neighbors_observed,
        raw_max_neighbors > _COMPILER_CAPS["max_neighbors"],
    )


def _timed_blind_compile(
    compiler: CategoryCompiler,
    epoch_id: str,
    context_id: str,
    seed_ids: Sequence[str],
    purpose: str,
    proxy_to_opaque: Mapping[str, str],
    adjacency: Mapping[str, set[str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    started = time.monotonic_ns()
    compiled = compiler.compile(epoch_id, context_id=context_id, seed_cell_ids=seed_ids)
    elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
    rows: list[dict[str, object]] = []
    for cell in compiled.cells:
        try:
            candidate_id = proxy_to_opaque[cell.id]
        except KeyError as exc:
            raise RuntimeError("compiler returned a cell outside BlindCorpus") from exc
        rows.append({
            "candidate_id": candidate_id,
            "score": float(cell.score),
            "contributions": {str(name): float(value) for name, value in cell.contributions.items()},
            "hops": int(cell.hops),
            "token_count": int(cell.token_count),
        })
    raw_max_neighbors, max_neighbors_observed, neighbor_limit_hit = (
        _neighbor_observations(rows, adjacency)
    )
    probe = {
        "purpose": purpose,
        "candidate_count": int(compiled.candidate_count),
        "cell_count": len(compiled.cells),
        "token_count": int(compiled.token_count),
        "truncated": bool(compiled.truncated),
        "rotation_required": bool(compiled.rotation_required),
        "elapsed_wall_time_ms": elapsed_ms,
        "max_hops": max((int(cell.hops) for cell in compiled.cells), default=0),
        "max_neighbors_observed": max_neighbors_observed,
        "raw_max_neighbors": raw_max_neighbors,
        "neighbor_limit_hit": neighbor_limit_hit,
    }
    return rows, probe


def _validate_ranking_output(output: object, corpus: object) -> dict[str, object]:
    corpus = _validate_blind_corpus(corpus)
    output = _require_exact_keys(output, {
        "schema", "schema_version", "fixture_hash", "corpus_hash", "encoder",
        "baseline_source", "compiler_limits", "fixture_import", "rankings",
    }, "RankingOutput")
    if (
        output["schema"] != RANKING_OUTPUT_SCHEMA
        or type(output["schema_version"]) is not int
        or output["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("RankingOutput schema/version is unsupported")
    if output["fixture_hash"] != corpus["fixture_hash"]:
        raise ValueError("RankingOutput fixture hash does not match BlindCorpus")
    if output["corpus_hash"] != _canonical_hash(corpus):
        raise ValueError("RankingOutput corpus hash does not match BlindCorpus")
    _validate_encoder(output["encoder"], "RankingOutput encoder")
    if output["baseline_source"] != "CategoryStore.search":
        raise ValueError("RankingOutput retrieval contract is invalid")
    compiler_limits = _require_exact_keys(
        output["compiler_limits"], set(_COMPILER_CAPS), "RankingOutput compiler limits",
    )
    if (
        compiler_limits != _COMPILER_CAPS
        or any(type(compiler_limits[name]) is not int for name in _COMPILER_CAPS)
    ):
        raise ValueError("RankingOutput compiler limits are not the fixed five caps")
    import_report = _require_exact_keys(output["fixture_import"], {
        "legacy_total", "proxy_zero_cells", "imported_one_cells", "imported_two_cells",
        "opaque_cells", "unexplained_loss", "root_epoch_id", "snapshot_hash",
    }, "RankingOutput fixture import")
    if any(type(import_report[name]) is not int or int(import_report[name]) < 0 for name in (
        "legacy_total", "proxy_zero_cells", "imported_one_cells", "imported_two_cells",
        "opaque_cells", "unexplained_loss",
    )):
        raise ValueError("RankingOutput fixture import counts are invalid")
    if (
        not isinstance(import_report["root_epoch_id"], str) or not import_report["root_epoch_id"]
        or not _valid_hash(import_report["snapshot_hash"])
    ):
        raise ValueError("RankingOutput fixture import identities are invalid")
    corpus_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    candidate_ids = {str(candidate["candidate_id"]) for candidate in corpus["candidates"]}
    adjacency = _blind_adjacency(corpus)
    rankings = output["rankings"]
    if not isinstance(rankings, list) or len(rankings) != len(corpus_cases):
        raise ValueError("RankingOutput cases are incomplete")
    seen: set[str] = set()
    for raw_case in rankings:
        case = _require_exact_keys(raw_case, {
            "case_id", "baseline", "direct", "shadow", "shadow_direct",
            "compiler_cells", "compiler_direct_cells", "compiler",
        }, "RankingOutput case")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or case_id not in corpus_cases or case_id in seen:
            raise ValueError("RankingOutput case IDs do not match BlindCorpus")
        seen.add(case_id)
        expected_level_zero = set(corpus_cases[case_id]["candidate_ids"])
        _validate_search_rows(case["baseline"], expected_level_zero, "baseline")
        _validate_search_rows(case["direct"], expected_level_zero, "direct")
        _validate_shadow_rows(case["compiler_cells"], candidate_ids, "compiler cells")
        _validate_shadow_rows(
            case["compiler_direct_cells"], candidate_ids, "direct compiler cells",
        )
        _validate_shadow_rows(case["shadow"], expected_level_zero, "shadow")
        _validate_shadow_rows(case["shadow_direct"], expected_level_zero, "shadow direct")
        if (
            {row["candidate_id"] for row in case["shadow"]} != expected_level_zero
            or {row["candidate_id"] for row in case["shadow_direct"]} != expected_level_zero
        ):
            raise ValueError(
                "RankingOutput shadow rankings must cover the complete declared candidate universe"
            )
        compiler = _require_exact_keys(case["compiler"], {"query", "direct"}, "RankingOutput compiler")
        _validate_compile_probe(
            compiler["query"], "query", case["compiler_cells"], adjacency,
        )
        _validate_compile_probe(
            compiler["direct"], "direct", case["compiler_direct_cells"], adjacency,
        )
        expected_shadow = [
            row for row in case["compiler_cells"]
            if row["candidate_id"] in expected_level_zero
        ]
        expected_shadow_direct = [
            row for row in case["compiler_direct_cells"]
            if row["candidate_id"] in expected_level_zero
        ]
        if case["shadow"] != expected_shadow or case["shadow_direct"] != expected_shadow_direct:
            raise ValueError("RankingOutput shadow projection does not match declared candidates")
    if seen != set(corpus_cases):
        raise ValueError("RankingOutput cases do not cover BlindCorpus")
    return output


def _validate_search_rows(rows: object, expected_ids: set[str], label: str) -> None:
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise ValueError(f"RankingOutput {label} ranking is incomplete")
    seen: set[str] = set()
    previous_distance = -math.inf
    for raw_row in rows:
        row = _require_exact_keys(raw_row, {"candidate_id", "distance"}, f"RankingOutput {label} row")
        identifier = row["candidate_id"]
        distance = row["distance"]
        if not isinstance(identifier, str) or identifier not in expected_ids or identifier in seen:
            raise ValueError(f"RankingOutput {label} candidate IDs are invalid")
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(float(distance)) or distance < 0:
            raise ValueError(f"RankingOutput {label} distance is invalid")
        if float(distance) < previous_distance:
            raise ValueError(f"RankingOutput {label} distance order is invalid")
        previous_distance = float(distance)
        seen.add(identifier)
    if seen != expected_ids:
        raise ValueError(f"RankingOutput {label} ranking is incomplete")


def _validate_shadow_rows(rows: object, allowed_ids: set[str], label: str) -> None:
    if not isinstance(rows, list):
        raise ValueError(f"RankingOutput {label} must be an array")
    seen: set[str] = set()
    for raw_row in rows:
        row = _require_exact_keys(raw_row, {
            "candidate_id", "score", "contributions", "hops", "token_count",
        }, f"RankingOutput {label} row")
        identifier = row["candidate_id"]
        if not isinstance(identifier, str) or identifier not in allowed_ids or identifier in seen:
            raise ValueError(f"RankingOutput {label} candidate IDs are invalid")
        seen.add(identifier)
        score = row["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise ValueError(f"RankingOutput {label} score is invalid")
        contributions = row["contributions"]
        if not isinstance(contributions, dict) or any(
            not isinstance(name, str) or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(float(value))
            for name, value in contributions.items()
        ):
            raise ValueError(f"RankingOutput {label} contributions are invalid")
        if type(row["hops"]) is not int or row["hops"] < 0:
            raise ValueError(f"RankingOutput {label} hops are invalid")
        if type(row["token_count"]) is not int or row["token_count"] < 0:
            raise ValueError(f"RankingOutput {label} token count is invalid")


def _validate_compile_probe(
    probe: object,
    purpose: str,
    rows: object,
    adjacency: Mapping[str, set[str]],
) -> None:
    probe = _require_exact_keys(probe, {
        "purpose", "candidate_count", "cell_count", "token_count", "truncated",
        "rotation_required", "elapsed_wall_time_ms", "max_hops", "max_neighbors_observed",
        "raw_max_neighbors", "neighbor_limit_hit",
    }, "RankingOutput compiler observation")
    if not isinstance(rows, list):
        raise ValueError("RankingOutput compiler rows must be an array")
    if probe["purpose"] != purpose or probe["cell_count"] != len(rows):
        raise ValueError("RankingOutput compiler observation does not match its ranking")
    for name in (
        "candidate_count", "cell_count", "token_count", "max_hops",
        "max_neighbors_observed", "raw_max_neighbors",
    ):
        if type(probe[name]) is not int or probe[name] < 0:
            raise ValueError("RankingOutput compiler counts must be non-negative integers")
    if probe["candidate_count"] < probe["cell_count"]:
        raise ValueError("RankingOutput compiler candidate count is inconsistent")
    if (
        type(probe["truncated"]) is not bool
        or type(probe["rotation_required"]) is not bool
        or type(probe["neighbor_limit_hit"]) is not bool
    ):
        raise ValueError("RankingOutput compiler flags must be bool")
    observed_max_hops = max((int(row["hops"]) for row in rows), default=0)
    if probe["max_hops"] != observed_max_hops:
        raise ValueError("RankingOutput compiler maximum hops contradicts its rows")
    observed_tokens = sum(int(row["token_count"]) for row in rows)
    if probe["token_count"] != observed_tokens:
        raise ValueError("RankingOutput compiler token count contradicts its rows")
    expected_raw, expected_effective, expected_limit_hit = _neighbor_observations(
        rows, adjacency,
    )
    if (
        probe["raw_max_neighbors"] != expected_raw
        or probe["max_neighbors_observed"] != expected_effective
        or probe["neighbor_limit_hit"] is not expected_limit_hit
    ):
        raise ValueError("RankingOutput compiler neighbor observations contradict graph rows")
    if (
        (probe["neighbor_limit_hit"] or probe["candidate_count"] > probe["cell_count"])
        and not probe["truncated"]
    ):
        raise ValueError("RankingOutput compiler truncation flag is inconsistent")
    elapsed = probe["elapsed_wall_time_ms"]
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(float(elapsed)) or elapsed < 0:
        raise ValueError("RankingOutput compiler elapsed time is invalid")


def _score_ranking_output(
    output: object,
    adjudication: object,
    corpus: object,
) -> dict[str, object]:
    """Join validated child output to validated parent gold after child exit."""
    corpus = _validate_blind_corpus(corpus)
    output = _validate_ranking_output(output, corpus)
    adjudication = _validate_adjudication(adjudication, corpus)
    output_by_case = {str(case["case_id"]): case for case in output["rankings"]}
    baseline_rankings = []
    shadow_rankings = []
    direct_baseline_rankings = []
    direct_shadow_rankings = []
    transfer_events: list[bool] = []
    for gold in adjudication["ranking_cases"]:
        completed = output_by_case[str(gold["case_id"])]
        relevant = set(gold["relevant_ids"])
        baseline_ids = [str(row["candidate_id"]) for row in completed["baseline"]]
        direct_ids = [str(row["candidate_id"]) for row in completed["direct"]]
        shadow_ids = [str(row["candidate_id"]) for row in completed["shadow"]]
        shadow_direct_ids = [str(row["candidate_id"]) for row in completed["shadow_direct"]]
        baseline_rankings.append((baseline_ids, relevant))
        shadow_rankings.append((shadow_ids, relevant))
        direct_baseline_rankings.append((direct_ids, relevant))
        direct_shadow_rankings.append((shadow_direct_ids, relevant))
        labels = gold["candidate_context_labels"]
        relevant_labels = {labels[identifier] for identifier in relevant}
        relevant_position = min(
            (index for index, identifier in enumerate(shadow_ids) if identifier in relevant),
            default=None,
        )
        for opportunity in gold["negative_transfer_opportunities"]:
            opportunity_position = shadow_ids.index(opportunity) if opportunity in shadow_ids else None
            is_foreign = labels[opportunity] not in relevant_labels
            transfer_events.append(bool(
                gold["negative_transfer_truth"][opportunity]
                and is_foreign
                and opportunity_position is not None
                and (relevant_position is None or opportunity_position < relevant_position)
            ))
    baseline_mrr = mean_reciprocal_rank(baseline_rankings)
    shadow_mrr = mean_reciprocal_rank(shadow_rankings)
    baseline_hits = sum(bool(ranking and ranking[0] in relevant) for ranking, relevant in direct_baseline_rankings)
    shadow_hits = sum(bool(ranking and ranking[0] in relevant) for ranking, relevant in direct_shadow_rankings)
    compile_probes = [
        completed["compiler"][purpose]
        for completed in output["rankings"]
        for purpose in ("query", "direct")
    ]
    return {
        "source": "category_compiler_fixture_db",
        "execution": "validated_blind_subprocess",
        "baseline_source": output["baseline_source"],
        "baseline_mrr": baseline_mrr,
        "shadow_mrr": shadow_mrr,
        "relative_mrr_improvement": relative_mrr_improvement(baseline_mrr, shadow_mrr),
        "direct_recall_baseline_hits": baseline_hits,
        "direct_recall_shadow_hits": shadow_hits,
        "direct_recall_regression": direct_recall_regression(baseline_hits, shadow_hits),
        "direct_recall_evaluated": baseline_hits > 0,
        "false_transfer_rate": false_transfer_rate(transfer_events) if transfer_events else None,
        "false_transfer_evaluated": bool(transfer_events),
        "false_transfer_opportunities": len(transfer_events),
        "fixture_import": output["fixture_import"],
        "direct_seed_source": "baseline_direct_top",
        "cross_context_pairs": len(adjudication["ranking_cases"]),
        "cross_context_candidates_evaluated": len(transfer_events),
        "labels_blinded_from_ranking": True,
        "compile_probes": compile_probes,
        "ranking_output_hash": _canonical_hash(output),
    }


def _predict_boundary_decisions(
    cohort: FixtureCohort,
    configuration: Mapping[str, object],
) -> list[dict[str, object]]:
    blind_corpus, _adjudication = _build_blinded_inputs(cohort)
    return _run_blinded_boundaries(blind_corpus, configuration)["predictions"]


def _score_boundary_predictions(
    predictions: Sequence[Mapping[str, object]],
    adjudication: Mapping[str, object],
) -> dict[str, dict[str, float | int]]:
    predicted = {str(case["case_id"]): case["decisions"] for case in predictions}
    rows: list[tuple[str, bool, bool]] = []
    for gold in adjudication["boundary_cases"]:
        case_id = str(gold["case_id"])
        if case_id not in predicted or not isinstance(predicted[case_id], list):
            raise ValueError("boundary predictions do not match Adjudication")
        decisions = predicted[case_id]
        if len(decisions) != len(gold["expected_decisions"]):
            raise ValueError("boundary prediction/Adjudication lengths differ")
        for expected, observed in zip(gold["expected_decisions"], decisions, strict=True):
            if type(observed) is not bool:
                raise ValueError("boundary predictions must be bool")
            rows.append((str(gold["kind"]), bool(expected), observed))
    if set(predicted) != {str(case["case_id"]) for case in adjudication["boundary_cases"]}:
        raise ValueError("boundary predictions do not cover Adjudication")
    return boundary_metrics(rows)


def _load_vec(connection: sqlite3.Connection) -> None:
    connection.enable_load_extension(True)
    try:
        sqlite_vec.load(connection)
    finally:
        connection.enable_load_extension(False)


def _fixture_vector(text: str) -> list[float]:
    """Fixed text-only encoder shared by documents, queries, and direct queries."""
    values = [0.0] * ENCODER_DIMENSIONS
    tokens = re.findall(r"\w+", text.casefold())
    features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
    for feature in features:
        digest = hashlib.sha256((ENCODER_SEED + feature).encode()).digest()
        index = int.from_bytes(digest[:4], "big") % ENCODER_DIMENSIONS
        values[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


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
    """Digest all replayed category state while excluding runtime timestamps."""
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = [str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cat_%' ORDER BY name"
        ) if not str(row[0]).startswith("cat_vectors")]
        state: dict[str, object] = {"import_report": import_report, "tables": {}}
        for table in tables:
            table_info = list(connection.execute(f'PRAGMA table_info("{table}")'))
            columns = [str(row[1]) for row in table_info
                       if str(row[1]) not in {"created_at", "applied_at"}]
            primary_key = [
                str(row[1])
                for row in sorted(table_info, key=lambda item: int(item[5]))
                if int(row[5]) > 0
            ]
            definition = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            without_rowid = bool(
                definition is not None
                and isinstance(definition[0], str)
                and "WITHOUT ROWID" in definition[0].upper()
            )
            order_by = primary_key if without_rowid else ["rowid"]
            rows = connection.execute(
                f'SELECT {",".join(chr(34)+column+chr(34) for column in columns)} '
                f'FROM "{table}" ORDER BY '
                + ",".join(chr(34) + column + chr(34) for column in order_by)
            ).fetchall()
            state["tables"][table] = {"columns": columns, "rows": [list(row) for row in rows]}
        return hashlib.sha256(_canonical_json(state).encode()).hexdigest()
    finally:
        connection.close()


def _compile_probe(database: Path, epoch_id: str) -> dict[str, object]:
    connection = sqlite3.connect(database)
    store = EvolvingCategoryStore(connection)
    compiler = CategoryCompiler(store, CompileBudget())
    try:
        row = connection.execute("SELECT id FROM cat_cells ORDER BY id LIMIT 1").fetchone()
        started = time.monotonic_ns()
        compiled = compiler.compile(epoch_id, seed_cell_ids=(() if row is None else (str(row[0]),)))
        elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
        connection.execute(
            "CREATE TEMP TABLE category_eval_compiled (id TEXT PRIMARY KEY, hops INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO category_eval_compiled (id, hops) VALUES (?, ?)",
            ((str(cell.id), int(cell.hops)) for cell in compiled.cells),
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
                FROM category_eval_compiled AS expanded
                LEFT JOIN adjacency ON adjacency.node_id = expanded.id
                WHERE expanded.hops < ?
                GROUP BY expanded.id
            )
        """, (_COMPILER_CAPS["max_depth"],)).fetchone()[0])
        max_neighbors_observed = int(connection.execute(f"""
            WITH adjacency AS ({adjacency_sql})
            SELECT COALESCE(MAX(neighbor_count), 0)
            FROM (
                SELECT expanded.id, COUNT(DISTINCT admitted.id) AS neighbor_count
                FROM category_eval_compiled AS expanded
                LEFT JOIN adjacency ON adjacency.node_id = expanded.id
                LEFT JOIN category_eval_compiled AS admitted
                    ON admitted.id = adjacency.neighbor_id
                WHERE expanded.hops < ?
                GROUP BY expanded.id
            )
        """, (_COMPILER_CAPS["max_depth"],)).fetchone()[0])
        return {
            "purpose": "legacy_replay",
            "candidate_count": compiled.candidate_count,
            "cell_count": len(compiled.cells),
            "token_count": compiled.token_count,
            "truncated": compiled.truncated,
            "rotation_required": compiled.rotation_required,
            "elapsed_wall_time_ms": elapsed_ms,
            "max_hops": max((cell.hops for cell in compiled.cells), default=0),
            "max_neighbors_observed": max_neighbors_observed,
            "raw_max_neighbors": raw_max_neighbors,
            "neighbor_limit_hit": raw_max_neighbors > _COMPILER_CAPS["max_neighbors"],
        }
    finally:
        compiler.close()
        store.close()


def _compiler_probe_conforms(probe: object, limits: object) -> bool:
    if not isinstance(probe, dict) or limits != _COMPILER_CAPS:
        return False
    integer_fields = (
        "max_hops", "max_neighbors_observed", "raw_max_neighbors",
        "candidate_count", "token_count",
    )
    if any(type(probe.get(name)) is not int or int(probe[name]) < 0 for name in integer_fields):
        return False
    elapsed = probe.get("elapsed_wall_time_ms")
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or float(elapsed) < 0
        or type(probe.get("neighbor_limit_hit")) is not bool
    ):
        return False
    if "ran" in probe and probe["ran"] is not True:
        return False
    return bool(
        int(probe["max_hops"]) <= _COMPILER_CAPS["max_depth"]
        and int(probe["max_neighbors_observed"]) <= _COMPILER_CAPS["max_neighbors"]
        and int(probe["max_neighbors_observed"]) <= int(probe["raw_max_neighbors"])
        and probe["neighbor_limit_hit"]
        is (int(probe["raw_max_neighbors"]) > _COMPILER_CAPS["max_neighbors"])
        and int(probe["candidate_count"]) <= _COMPILER_CAPS["max_candidates"]
        and float(elapsed) <= _COMPILER_CAPS["wall_time_ms"]
        and int(probe["token_count"]) <= _COMPILER_CAPS["hard_ceiling"]
    )


def _acceptance(report: dict[str, object]) -> dict[str, object]:
    boundary = report["boundary_metrics"]
    ranking = report["ranking"]
    assert isinstance(boundary, dict) and isinstance(ranking, dict)
    overall = boundary["overall"]
    assert isinstance(overall, dict)
    relative = ranking["relative_mrr_improvement"]
    raw_compiler_probes = report.get("compiler_probes", [])
    compiler_probes = list(raw_compiler_probes) if isinstance(raw_compiler_probes, list) else []
    limits = report.get("compiler_limits")
    resource_benchmark = report["resource_benchmark"]
    if isinstance(resource_benchmark, dict) and isinstance(resource_benchmark.get("compiler"), dict):
        resource_probe = resource_benchmark["compiler"]
        if resource_probe not in compiler_probes:
            compiler_probes.append(resource_probe)
    import_reports = report.get("import_reports")
    replay_losses = None if not isinstance(import_reports, list) else [
        int(item["unexplained_loss"]) for item in import_reports
    ]
    compiler_conformant = (
        limits == _COMPILER_CAPS
        and bool(compiler_probes)
        and all(_compiler_probe_conforms(probe, limits) for probe in compiler_probes)
    )
    resource_evaluated = (
        isinstance(resource_benchmark, dict)
        and isinstance(resource_benchmark.get("acceptance_gate"), dict)
        and resource_benchmark["acceptance_gate"].get("evaluated") is True
    )
    resource_observed = None if not isinstance(resource_benchmark, dict) else resource_benchmark.get("incremental_peak_rss_bytes")
    resource_passed = (
        resource_evaluated
        and isinstance(resource_observed, int)
        and resource_observed < RSS_GATE_BYTES
        and resource_benchmark["acceptance_gate"].get("passed") is True
    )
    gates = {
        "ranking_blinded": _gate(True, report.get("ranking_blinded"), report.get("ranking_blinded") is True),
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
        "compiler_conformance": _gate(_COMPILER_CAPS, compiler_probes, compiler_conformant),
        "incremental_peak_rss": _gate(
            GATE_THRESHOLDS["incremental_peak_rss_bytes"], resource_observed, resource_passed,
        ),
    }
    return {
        "thresholds": GATE_THRESHOLDS,
        "gates": gates,
        "overall_pass": all(gate["passed"] for gate in gates.values()),
    }


def _gate(threshold: object, observed: object, passed: bool) -> dict[str, object]:
    return {"threshold": threshold, "observed": observed, "passed": passed}


RSS_GATE_BYTES = 1 << 30


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=lambda item: {"blob": item.hex()} if isinstance(item, bytes) else _raise_json_type(item),
    )


def _raise_json_type(value: object) -> object:
    raise TypeError(type(value).__name__)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == _RANKING_WORKER_FLAG:
        if arguments != [_RANKING_WORKER_FLAG]:
            print("error: private ranking worker accepts stdin JSON only", file=sys.stderr)
            return 2
        return _ranking_worker_main()
    if arguments and arguments[0] == _BOUNDARY_WORKER_FLAG:
        if arguments != [_BOUNDARY_WORKER_FLAG]:
            print("error: private boundary worker accepts stdin JSON only", file=sys.stderr)
            return 2
        return _boundary_worker_main()
    try:
        args = build_parser().parse_args(arguments)
        report = run_evaluation(args)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
