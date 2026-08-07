"""Domain-neutral inference of boundaries between sparse observation contexts."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite
from types import MappingProxyType
from typing import Literal


_MAP_FIELDS = ("goal", "entities", "participants", "tools", "sources", "attention")
_SOFT_THRESHOLD = 0.35
_HARD_THRESHOLD = 0.65
_MAX_FINGERPRINTS = 16


@dataclass(frozen=True)
class ContextObservation:
    goal: Mapping[str, float] = field(default_factory=dict)
    entities: Mapping[str, float] = field(default_factory=dict)
    participants: Mapping[str, float] = field(default_factory=dict)
    tools: Mapping[str, float] = field(default_factory=dict)
    sources: Mapping[str, float] = field(default_factory=dict)
    attention: Mapping[str, float] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    explicit_boundary: bool = False


@dataclass(frozen=True)
class BoundaryDecision:
    kind: Literal["same", "soft", "hard"]
    score: float
    confirmations: int
    components: Mapping[str, float]
    context_id: str


@dataclass(frozen=True)
class _Snapshot:
    maps: tuple[tuple[tuple[str, float], ...], ...]
    observed_at: datetime


class ContextTracker:
    """Tracks a stable context and confirms inferred changes before switching IDs.

    Scores at or above the soft threshold are qualifying observations.  A hard
    decision is emitted only once the configured number of consecutive
    qualifying observations has been received against the current stable
    anchor.  The 0.65 threshold is retained as the severity boundary for
    callers that inspect scores; it never bypasses confirmation.
    """

    def __init__(
        self,
        *,
        hard_confirmations: int = 2,
        temporal_gap: timedelta = timedelta(minutes=30),
    ) -> None:
        if isinstance(hard_confirmations, bool) or not isinstance(hard_confirmations, int):
            raise TypeError("hard_confirmations must be an integer")
        if hard_confirmations < 2:
            raise ValueError("hard_confirmations must be an integer of at least 2")
        if not isinstance(temporal_gap, timedelta) or temporal_gap <= timedelta(0):
            raise ValueError("temporal_gap must be a positive timedelta")

        self._hard_confirmations = hard_confirmations
        self._temporal_gap = temporal_gap
        self._anchor: _Snapshot | None = None
        self._last_observed_at: datetime | None = None
        self._confirmations = 0
        self._context_id: str | None = None
        self._next_context_number = 1
        self._fingerprints: deque[tuple[tuple[tuple[str, float], ...], ...], str] = deque(
            maxlen=_MAX_FINGERPRINTS
        )

    def observe(self, observation: ContextObservation) -> BoundaryDecision:
        """Record one observation and return its relationship to the stable context.

        Timestamps must be timezone-aware and nondecreasing.  Empty maps are
        valid: two empty maps have zero divergence, while an empty/non-empty
        pair has full divergence.  Values must be finite, non-negative reals.
        """
        snapshot = _snapshot(observation)
        if self._last_observed_at is not None and snapshot.observed_at < self._last_observed_at:
            raise ValueError("observations must be in nondecreasing time order")

        if self._anchor is None:
            self._context_id = self._new_context_id()
            self._anchor = snapshot
            self._last_observed_at = snapshot.observed_at
            self._remember(snapshot.maps, self._context_id)
            if observation.explicit_boundary:
                return self._decision(
                    "hard", 1.0, self._hard_confirmations, _zero_components(), self._context_id
                )
            return self._decision("same", 0.0, 0, _zero_components(), self._context_id)

        assert self._context_id is not None
        components = _components(self._anchor.maps, snapshot.maps, self._time_component(snapshot))
        inferred_score = _score(components)
        self._last_observed_at = snapshot.observed_at

        if observation.explicit_boundary:
            self._context_id = self._new_context_id()
            self._anchor = snapshot
            self._confirmations = 0
            self._remember(snapshot.maps, self._context_id)
            return self._decision(
                "hard", 1.0, self._hard_confirmations, components, self._context_id
            )

        if inferred_score < _SOFT_THRESHOLD:
            self._confirmations = 0
            self._anchor = snapshot
            self._remember(snapshot.maps, self._context_id)
            return self._decision("same", inferred_score, 0, components, self._context_id)

        self._confirmations += 1
        if self._confirmations < self._hard_confirmations:
            return self._decision(
                "soft", inferred_score, self._confirmations, components, self._context_id
            )

        self._context_id = self._known_context_id(snapshot.maps) or self._new_context_id()
        self._anchor = snapshot
        confirmed = self._confirmations
        self._confirmations = 0
        self._remember(snapshot.maps, self._context_id)
        return self._decision("hard", inferred_score, confirmed, components, self._context_id)

    def _time_component(self, snapshot: _Snapshot) -> float:
        assert self._last_observed_at is not None
        return float(snapshot.observed_at - self._last_observed_at >= self._temporal_gap)

    def _new_context_id(self) -> str:
        context_id = f"context-{self._next_context_number}"
        self._next_context_number += 1
        return context_id

    def _known_context_id(
        self, fingerprint: tuple[tuple[tuple[str, float], ...], ...]
    ) -> str | None:
        for known_fingerprint, context_id in reversed(self._fingerprints):
            if known_fingerprint == fingerprint:
                return context_id
        return None

    def _remember(
        self,
        fingerprint: tuple[tuple[tuple[str, float], ...], ...],
        context_id: str,
    ) -> None:
        self._fingerprints.append((fingerprint, context_id))

    @staticmethod
    def _decision(
        kind: Literal["same", "soft", "hard"],
        score: float,
        confirmations: int,
        components: Mapping[str, float],
        context_id: str,
    ) -> BoundaryDecision:
        return BoundaryDecision(
            kind=kind,
            score=score,
            confirmations=confirmations,
            components=MappingProxyType(dict(components)),
            context_id=context_id,
        )


def _snapshot(observation: ContextObservation) -> _Snapshot:
    if not isinstance(observation, ContextObservation):
        raise TypeError("observation must be a ContextObservation")
    if not isinstance(observation.explicit_boundary, bool):
        raise TypeError("explicit_boundary must be a bool")
    observed_at = observation.observed_at
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("observed_at must be a timezone-aware datetime")
    if observed_at.utcoffset() is None:
        raise ValueError("observed_at must be a timezone-aware datetime")

    maps = tuple(_normalise_map(getattr(observation, field_name), field_name) for field_name in _MAP_FIELDS)
    return _Snapshot(maps=maps, observed_at=observed_at)


def _normalise_map(values: Mapping[str, float], field_name: str) -> tuple[tuple[str, float], ...]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalised: list[tuple[str, float]] = []
    for key, value in values.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field_name} values must be real numbers")
        weight = float(value)
        if not isfinite(weight) or weight < 0:
            raise ValueError(f"{field_name} values must be finite and non-negative")
        normalised.append((key, weight))
    return tuple(sorted(normalised))


def _divergence(
    before: tuple[tuple[str, float], ...], after: tuple[tuple[str, float], ...]
) -> float:
    before_values = dict(before)
    after_values = dict(after)
    keys = before_values.keys() | after_values.keys()
    denominator = sum(max(before_values.get(key, 0.0), after_values.get(key, 0.0)) for key in keys)
    if denominator == 0:
        return 0.0
    numerator = sum(min(before_values.get(key, 0.0), after_values.get(key, 0.0)) for key in keys)
    return 1.0 - numerator / denominator


def _components(
    before: tuple[tuple[tuple[str, float], ...], ...],
    after: tuple[tuple[tuple[str, float], ...], ...],
    temporal_discontinuity: float,
) -> dict[str, float]:
    goal, entities, participants, tools, sources, _attention = range(6)
    return {
        "goal_divergence": _divergence(before[goal], after[goal]),
        "entity_turnover": _divergence(before[entities], after[entities]),
        "participant_turnover": _divergence(before[participants], after[participants]),
        "tool_turnover": _divergence(before[tools], after[tools]),
        "source_change": _divergence(before[sources], after[sources]),
        "temporal_discontinuity": temporal_discontinuity,
    }


def _zero_components() -> dict[str, float]:
    return {
        "goal_divergence": 0.0,
        "entity_turnover": 0.0,
        "participant_turnover": 0.0,
        "tool_turnover": 0.0,
        "source_change": 0.0,
        "temporal_discontinuity": 0.0,
    }


def _score(components: Mapping[str, float]) -> float:
    return (
        0.40 * components["goal_divergence"]
        + 0.20 * components["entity_turnover"]
        + 0.15
        * max(components["participant_turnover"], components["tool_turnover"])
        + 0.15 * components["source_change"]
        + 0.10 * components["temporal_discontinuity"]
    )
