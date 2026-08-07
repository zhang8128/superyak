from datetime import datetime, timedelta, timezone

import pytest

from category_context import ContextObservation, ContextTracker


@pytest.mark.parametrize(
    "before,after",
    [
        ({"goal:understand": 1.0}, {"goal:decide": 1.0}),
        ({"goal:debug": 1.0}, {"goal:deploy": 1.0}),
        ({"goal:follow": 1.0}, {"goal:compare": 1.0}),
        ({"goal:collect": 1.0}, {"goal:schedule": 1.0}),
    ],
)
def test_one_algorithm_detects_goal_shift(before, after):
    """Removing the shared goal must create a confirmed boundary, regardless of labels."""
    tracker = ContextTracker(hard_confirmations=2)

    tracker.observe(ContextObservation(goal=before))
    assert tracker.observe(ContextObservation(goal=after)).kind == "soft"
    assert tracker.observe(ContextObservation(goal=after)).kind == "hard"


def test_explicit_boundary_is_immediately_hard_with_a_perfect_score():
    """An explicit signal must not wait for inference confirmations."""
    tracker = ContextTracker()
    tracker.observe(ContextObservation(goal={"any": 1.0}))

    decision = tracker.observe(
        ContextObservation(goal={"any": 1.0}, explicit_boundary=True)
    )

    assert decision.kind == "hard"
    assert decision.score == 1.0


def test_initial_explicit_boundary_is_immediately_hard_with_a_perfect_score():
    """The explicit-boundary contract also applies before ordinary evidence exists."""
    decision = ContextTracker().observe(ContextObservation(explicit_boundary=True))

    assert decision.kind == "hard"
    assert decision.score == 1.0


def test_weighted_overlap_reduces_goal_divergence():
    """Shared weighted evidence must lower the weighted-Jaccard goal component."""
    tracker = ContextTracker()
    tracker.observe(ContextObservation(goal={"shared": 1.0, "old": 1.0}))

    decision = tracker.observe(ContextObservation(goal={"shared": 1.0, "new": 1.0}))

    assert decision.components["goal_divergence"] == pytest.approx(2 / 3)
    assert decision.score == pytest.approx((2 / 3) * 0.40)
    assert decision.kind == "same"


def test_goal_only_change_is_soft_then_hard_after_confirmation():
    """A goal-only score of 0.40 must be confirmed rather than accepted immediately."""
    tracker = ContextTracker(hard_confirmations=2)
    tracker.observe(ContextObservation(goal={"first": 1.0}))

    first = tracker.observe(ContextObservation(goal={"second": 1.0}))
    second = tracker.observe(ContextObservation(goal={"second": 1.0}))

    assert (first.kind, first.score, first.confirmations) == ("soft", 0.40, 1)
    assert (second.kind, second.score, second.confirmations) == ("hard", 0.40, 2)


def test_source_only_change_does_not_cross_the_soft_threshold():
    """Sources alone contribute only their configured 0.15 weight."""
    tracker = ContextTracker()
    tracker.observe(ContextObservation(sources={"source:a": 1.0}))

    decision = tracker.observe(ContextObservation(sources={"source:b": 1.0}))

    assert decision.components["source_change"] == 1.0
    assert decision.score == 0.15
    assert decision.kind == "same"


def test_gradual_drift_below_soft_threshold_remains_in_the_same_context():
    """Small successive weighted changes must not accumulate into a boundary by themselves."""
    tracker = ContextTracker()
    initial = tracker.observe(ContextObservation(goal={"steady": 1.0}))

    first = tracker.observe(ContextObservation(goal={"steady": 0.9, "nearby": 0.1}))
    second = tracker.observe(ContextObservation(goal={"steady": 0.8, "nearby": 0.2}))

    assert first.kind == second.kind == "same"
    assert first.context_id == second.context_id == initial.context_id


def test_return_to_a_prior_fingerprint_reactivates_its_context_id():
    """A confirmed return must preserve the original stable context identity."""
    tracker = ContextTracker(hard_confirmations=2)
    first = tracker.observe(ContextObservation(goal={"first": 1.0}))
    second = tracker.observe(ContextObservation(goal={"second": 1.0}))
    changed = tracker.observe(ContextObservation(goal={"second": 1.0}))

    assert second.kind == "soft"
    assert changed.kind == "hard"
    assert tracker.observe(ContextObservation(goal={"first": 1.0})).kind == "soft"
    returned = tracker.observe(ContextObservation(goal={"first": 1.0}))

    assert returned.kind == "hard"
    assert returned.context_id == first.context_id


def test_time_discontinuity_is_scored_without_reclassifying_stable_evidence():
    """A large clock gap must be visible in the score but cannot exceed 0.35 alone."""
    tracker = ContextTracker(temporal_gap=timedelta(minutes=30))
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracker.observe(ContextObservation(goal={"same": 1.0}, observed_at=started))

    decision = tracker.observe(
        ContextObservation(
            goal={"same": 1.0}, observed_at=started + timedelta(minutes=31)
        )
    )

    assert decision.components["temporal_discontinuity"] == 1.0
    assert decision.score == 0.10
    assert decision.kind == "same"


def test_stable_observations_keep_the_context_and_clear_confirmations():
    """A below-soft observation must cancel a pending inferred boundary."""
    tracker = ContextTracker(hard_confirmations=2)
    original = tracker.observe(ContextObservation(goal={"first": 1.0}))
    pending = tracker.observe(ContextObservation(goal={"second": 1.0}))
    stable = tracker.observe(ContextObservation(goal={"first": 1.0}))

    assert pending.confirmations == 1
    assert stable.kind == "same"
    assert stable.confirmations == 0
    assert stable.context_id == original.context_id


def test_empty_maps_have_zero_divergence_and_keep_a_stable_context():
    """Two observations without evidence describe the same sparse context."""
    tracker = ContextTracker()
    first = tracker.observe(ContextObservation())
    second = tracker.observe(ContextObservation())

    assert second.kind == "same"
    assert second.score == 0.0
    assert second.context_id == first.context_id


@pytest.mark.parametrize(
    "observation",
    [
        ContextObservation(goal={"bad": float("nan")}),
        ContextObservation(goal={"bad": -1.0}),
        ContextObservation(goal={1: 1.0}),  # type: ignore[dict-item]
        ContextObservation(goal={"bad": float("inf")}),
        ContextObservation(observed_at=datetime(2026, 1, 1)),
    ],
)
def test_invalid_observations_are_rejected_before_scoring(observation):
    """Invalid weights and ambiguous timestamps must never leak into a decision score."""
    with pytest.raises((TypeError, ValueError)):
        ContextTracker().observe(observation)


def test_out_of_order_observations_are_rejected():
    """Rejecting backward time keeps discontinuity calculations deterministic."""
    tracker = ContextTracker()
    later = datetime(2026, 1, 2, tzinfo=timezone.utc)
    tracker.observe(ContextObservation(observed_at=later))

    with pytest.raises(ValueError, match="nondecreasing"):
        tracker.observe(ContextObservation(observed_at=later - timedelta(seconds=1)))
