"""Metadata-only sanitization for operation attribution."""

from __future__ import annotations

import math
from collections.abc import Mapping


_SCALAR_FIELDS = {
    "remember": {"core", "genome", "work"},
    "instinct_feedback": {"followed"},
    "mark_core": {"tier"},
    "assessment_report": {"function_score"},
    "reindex": {"full"},
    "graph_view": {"depth"},
    "clipboard_pin": {"priority"},
    "clipboard_remind": {"value", "repeat"},
}

_BOOLEAN_FIELDS = {
    "remember": {"core", "genome", "work"},
    "instinct_feedback": {"followed"},
    "reindex": {"full"},
    "clipboard_remind": {"repeat"},
}

_ENUM_FIELDS = {
    "reflect": {
        "focus": {
            "usage",
            "gaps",
            "instincts",
            "contradictions",
            "vital_signs",
            "staleness",
            "instinct_contexts",
            "classifications",
            "resonances",
            "instinct_clusters",
            "coherence",
            "anchors",
            "assessments",
            "fidelity",
            "cohesion",
            "persistence",
        }
    },
    "jot": {
        "scope": {"project", "global"},
        "status": {"open", "deferred", "done"},
    },
    "erase": {"scope": {"project", "global"}},
    "clipboard_remind": {
        "trigger": {"every_n_steps", "interval_seconds", "once_at"}
    },
}


def _is_finite_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def sanitize_operation_details(
    operation: str, arguments: Mapping[str, object]
) -> dict[str, object]:
    """Return only approved, non-content metadata for an operation."""
    sanitized: dict[str, object] = {}

    scalar_fields = _SCALAR_FIELDS.get(operation, set())
    boolean_fields = _BOOLEAN_FIELDS.get(operation, set())
    for field in scalar_fields:
        if field not in arguments:
            continue
        value = arguments[field]
        if field in boolean_fields:
            if type(value) is bool:
                sanitized[field] = value
        elif _is_finite_number(value):
            sanitized[field] = value

    for field, allowed_values in _ENUM_FIELDS.get(operation, {}).items():
        value = arguments.get(field)
        if type(value) is str and value in allowed_values:
            sanitized[field] = value

    if operation == "compress_commit":
        summaries = arguments.get("summaries")
        if type(summaries) is list:
            sanitized["summary_count"] = len(summaries)

    return sanitized
