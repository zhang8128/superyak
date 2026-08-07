"""Domain-neutral inference of boundaries between sparse observation contexts."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import fsum, isfinite
from types import MappingProxyType
from typing import Literal


_MAP_FIELDS = ("goal", "entities", "participants", "tools", "sources", "attention")
_SOFT_THRESHOLD = 0.35
_HARD_THRESHOLD = 0.65
_MAX_FINGERPRINTS = 16
_MODERATE_REQUIRED_SCORE = 0.40
_Fingerprint = tuple[tuple[tuple[str, float], ...], ...]


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
    maps: _Fingerprint
    observed_at: datetime


class ContextTracker:
    """Tracks a stable context and confirms inferred changes before switching IDs.

    A score at or above the configured hard threshold needs consecutive evidence
    for one canonical candidate. Scores from the configured soft threshold up to
    the hard threshold also need one candidate, plus a cumulative score of 0.40
    for every configured confirmation. This preserves the moderate-evidence
    policy without allowing unrelated changes to pool their evidence.
    """

    def __init__(
        self,
        *,
        hard_confirmations: int = 2,
        temporal_gap: timedelta = timedelta(minutes=30),
        soft_threshold: float = _SOFT_THRESHOLD,
        hard_threshold: float = _HARD_THRESHOLD,
    ) -> None:
        if isinstance(hard_confirmations, bool) or not isinstance(hard_confirmations, int):
            raise TypeError("hard_confirmations must be an integer")
        if hard_confirmations < 2:
            raise ValueError("hard_confirmations must be an integer of at least 2")
        if not isinstance(temporal_gap, timedelta) or temporal_gap <= timedelta(0):
            raise ValueError("temporal_gap must be a positive timedelta")
        for name, value in (
            ("soft_threshold", soft_threshold),
            ("hard_threshold", hard_threshold),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a real number")
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0 <= soft_threshold < hard_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= soft < hard <= 1")

        self._hard_confirmations = hard_confirmations
        self._temporal_gap = temporal_gap
        self._soft_threshold = float(soft_threshold)
        self._hard_threshold = float(hard_threshold)
        self._anchor: _Snapshot | None = None
        self._last_observed_at: datetime | None = None
        self._pending_candidate: _Fingerprint | None = None
        self._pending_path: Literal["strong", "moderate"] | None = None
        self._pending_confirmations = 0
        self._pending_scores: list[float] = []
        self._context_id: str | None = None
        self._next_context_number = 1
        self._fingerprints: OrderedDict[_Fingerprint, str] = OrderedDict()

    def clone(self) -> ContextTracker:
        """Return an independent snapshot suitable for transactional publication."""
        cloned = ContextTracker(
            hard_confirmations=self._hard_confirmations,
            temporal_gap=self._temporal_gap,
            soft_threshold=self._soft_threshold,
            hard_threshold=self._hard_threshold,
        )
        cloned._anchor = self._anchor
        cloned._last_observed_at = self._last_observed_at
        cloned._pending_candidate = self._pending_candidate
        cloned._pending_path = self._pending_path
        cloned._pending_confirmations = self._pending_confirmations
        cloned._pending_scores = list(self._pending_scores)
        cloned._context_id = self._context_id
        cloned._next_context_number = self._next_context_number
        cloned._fingerprints = OrderedDict(self._fingerprints)
        return cloned

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
            self._clear_pending()
            self._remember(snapshot.maps, self._context_id)
            return self._decision(
                "hard", 1.0, self._hard_confirmations, components, self._context_id
            )

        if inferred_score < self._soft_threshold:
            self._clear_pending()
            self._anchor = snapshot
            self._remember(snapshot.maps, self._context_id)
            return self._decision("same", inferred_score, 0, components, self._context_id)

        path: Literal["strong", "moderate"] = (
            "strong" if inferred_score >= self._hard_threshold else "moderate"
        )
        if snapshot.maps != self._pending_candidate or path != self._pending_path:
            self._pending_candidate = snapshot.maps
            self._pending_path = path
            self._pending_confirmations = 0
            self._pending_scores = []
        self._pending_confirmations += 1
        self._pending_scores.append(inferred_score)
        confirmed = self._pending_confirmations >= self._hard_confirmations and (
            path == "strong"
            or fsum(self._pending_scores)
            >= fsum((_MODERATE_REQUIRED_SCORE,) * self._hard_confirmations)
        )
        if not confirmed:
            return self._decision(
                "soft",
                inferred_score,
                self._pending_confirmations,
                components,
                self._context_id,
            )

        self._context_id = self._known_context_id(snapshot.maps) or self._new_context_id()
        self._anchor = snapshot
        confirmations = self._pending_confirmations
        self._clear_pending()
        self._remember(snapshot.maps, self._context_id)
        return self._decision("hard", inferred_score, confirmations, components, self._context_id)

    def _time_component(self, snapshot: _Snapshot) -> float:
        assert self._last_observed_at is not None
        return float(snapshot.observed_at - self._last_observed_at >= self._temporal_gap)

    def _new_context_id(self) -> str:
        context_id = f"context-{self._next_context_number}"
        self._next_context_number += 1
        return context_id

    def _known_context_id(
        self, fingerprint: _Fingerprint
    ) -> str | None:
        return self._fingerprints.get(fingerprint)

    def _remember(
        self,
        fingerprint: _Fingerprint,
        context_id: str,
    ) -> None:
        self._fingerprints[fingerprint] = context_id
        self._fingerprints.move_to_end(fingerprint)
        if len(self._fingerprints) > _MAX_FINGERPRINTS:
            self._fingerprints.popitem(last=False)

    def _clear_pending(self) -> None:
        self._pending_candidate = None
        self._pending_path = None
        self._pending_confirmations = 0
        self._pending_scores = []

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
        if weight:
            normalised.append((key, weight))
    return tuple(sorted(normalised))


def _divergence(
    before: tuple[tuple[str, float], ...], after: tuple[tuple[str, float], ...]
) -> float:
    before_values = dict(before)
    after_values = dict(after)
    keys = before_values.keys() | after_values.keys()
    scale = max(
        (max(before_values.get(key, 0.0), after_values.get(key, 0.0)) for key in keys),
        default=0.0,
    )
    if scale == 0:
        return 0.0
    denominator = fsum(
        max(before_values.get(key, 0.0), after_values.get(key, 0.0)) / scale for key in keys
    )
    numerator = fsum(
        min(before_values.get(key, 0.0), after_values.get(key, 0.0)) / scale for key in keys
    )
    divergence = 1.0 - numerator / denominator
    if not isfinite(divergence):
        raise ArithmeticError("weighted-Jaccard divergence must be finite")
    return min(1.0, max(0.0, divergence))


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
    if not all(isfinite(value) and 0.0 <= value <= 1.0 for value in components.values()):
        raise ArithmeticError("boundary components must be finite values from zero to one")
    score = fsum(
        (
            0.40 * components["goal_divergence"],
            0.20 * components["entity_turnover"],
            0.15 * max(components["participant_turnover"], components["tool_turnover"]),
            0.15 * components["source_change"],
            0.10 * components["temporal_discontinuity"],
        )
    )
    if not isfinite(score):
        raise ArithmeticError("boundary score must be finite")
    return min(1.0, max(0.0, score))
