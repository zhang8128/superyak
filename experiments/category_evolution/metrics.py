"""Small, validated metric definitions used by the category evaluation harness."""

from __future__ import annotations

from collections.abc import Iterable, Sequence, Set
from math import isfinite
from typing import Literal


_BOUNDARY_KINDS = frozenset(("explicit", "abrupt", "gradual"))


def boundary_metrics(
    rows: Iterable[tuple[Literal["explicit", "abrupt", "gradual"], bool, bool]],
) -> dict[str, dict[str, float | int]]:
    """Return precision/recall/F1 overall and for every supplied boundary kind.

    Each row is ``(kind, expected_boundary, predicted_boundary)``.  An empty
    denominator is reported as 0.0 so reports remain numeric and comparable.
    """
    grouped: dict[str, list[tuple[bool, bool]]] = {"overall": []}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 3:
            raise ValueError("boundary rows must be (kind, expected, predicted) tuples")
        kind, expected, predicted = row
        if kind not in _BOUNDARY_KINDS:
            raise ValueError("boundary kind must be explicit, abrupt, or gradual")
        if type(expected) is not bool or type(predicted) is not bool:
            raise ValueError("boundary expected and predicted values must be bool")
        grouped.setdefault(kind, []).append((expected, predicted))
        grouped["overall"].append((expected, predicted))
    return {name: _binary_metrics(values) for name, values in grouped.items()}


def _binary_metrics(rows: Sequence[tuple[bool, bool]]) -> dict[str, float | int]:
    true_positive = sum(expected and predicted for expected, predicted in rows)
    false_positive = sum(not expected and predicted for expected, predicted in rows)
    false_negative = sum(expected and not predicted for expected, predicted in rows)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "count": len(rows),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def mean_reciprocal_rank(rankings: Iterable[tuple[Sequence[str], Set[str]]]) -> float:
    """Return MRR; no relevant hit and an empty cohort both deterministically score 0."""
    reciprocal_ranks: list[float] = []
    for ranking in rankings:
        if not isinstance(ranking, tuple) or len(ranking) != 2:
            raise ValueError("ranking must be a (ranked_ids, relevant_ids) tuple")
        ranked_ids, relevant_ids = ranking
        if not isinstance(ranked_ids, (list, tuple)) or not isinstance(relevant_ids, (set, frozenset)):
            raise ValueError("ranking must contain an ordered list/tuple and a set of relevant IDs")
        if any(not isinstance(identifier, str) for identifier in ranked_ids):
            raise ValueError("ranking IDs must be strings")
        if len(set(ranked_ids)) != len(ranked_ids):
            raise ValueError("ranking IDs must not contain duplicates")
        if any(not isinstance(identifier, str) for identifier in relevant_ids):
            raise ValueError("relevant IDs must be strings")
        reciprocal_ranks.append(next(
            (1.0 / position for position, identifier in enumerate(ranked_ids, start=1) if identifier in relevant_ids),
            0.0,
        ))
    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0


def relative_mrr_improvement(baseline: float, shadow: float) -> float | None:
    """Return ``(shadow-baseline)/baseline``; a zero baseline is undefined (None)."""
    _finite_metric("baseline MRR", baseline)
    _finite_metric("shadow MRR", shadow)
    if baseline == 0.0:
        return None
    return (shadow - baseline) / baseline


def direct_recall_regression(baseline_hits: int, shadow_hits: int) -> float:
    """Return lost direct hits / baseline direct hits; zero baseline has regression 0.0."""
    if type(baseline_hits) is not int or type(shadow_hits) is not int:
        raise ValueError("direct recall hit counts must be integers")
    if baseline_hits < 0 or shadow_hits < 0:
        raise ValueError("direct recall hit counts must be non-negative")
    if baseline_hits == 0:
        return 0.0
    return max(0.0, (baseline_hits - shadow_hits) / baseline_hits)


def false_transfer_rate(events: Iterable[bool]) -> float:
    """Return the fraction of transfer attempts labeled false; empty input is 0.0."""
    values = list(events)
    if any(type(value) is not bool for value in values):
        raise ValueError("false-transfer events must be bool")
    return sum(values) / len(values) if values else 0.0


def _finite_metric(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
