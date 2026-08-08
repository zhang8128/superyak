"""Falsifiable, disposable evaluation helpers for evolving-category memory."""

from .fixtures import fixture_cohort, fixture_hash
from .metrics import boundary_metrics, false_transfer_rate, mean_reciprocal_rank

__all__ = [
    "boundary_metrics",
    "false_transfer_rate",
    "fixture_cohort",
    "fixture_hash",
    "mean_reciprocal_rank",
]
