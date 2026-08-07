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


def test_zero_weight_entries_are_equivalent_to_empty_maps():
    """Zero-mass labels must not alter divergence or canonical context identity."""
    tracker = ContextTracker()
    initial = tracker.observe(ContextObservation(goal={"discarded": 0.0}))
    decision = tracker.observe(ContextObservation(goal={"also-discarded": 0.0}))

    assert decision.kind == "same"
    assert decision.score == 0.0
    assert decision.context_id == initial.context_id


def test_alternating_moderate_candidates_do_not_confirm_a_boundary():
    """Changing candidate fingerprints must reset moderate evidence."""
    tracker = ContextTracker(hard_confirmations=2)
    tracker.observe(ContextObservation(goal={"anchor": 1.0}))

    first = tracker.observe(ContextObservation(goal={"candidate-one": 1.0}))
    alternate = tracker.observe(ContextObservation(goal={"candidate-two": 1.0}))

    assert first.kind == alternate.kind == "soft"
    assert (first.confirmations, alternate.confirmations) == (1, 1)


def test_moderate_evidence_needs_the_configured_cumulative_score():
    """Two 0.35 observations are insufficient; a third reaches cumulative 1.05."""
    tracker = ContextTracker(hard_confirmations=2)
    tracker.observe(
        ContextObservation(entities={"anchor": 1.0}, sources={"anchor": 1.0})
    )
    candidate = ContextObservation(
        entities={"candidate": 1.0}, sources={"candidate": 1.0}
    )

    first = tracker.observe(candidate)
    second = tracker.observe(candidate)
    third = tracker.observe(candidate)

    assert (first.kind, first.confirmations, first.score) == ("soft", 1, 0.35)
    assert (second.kind, second.confirmations, second.score) == ("soft", 2, 0.35)
    assert (third.kind, third.confirmations, third.score) == ("hard", 3, 0.35)


def test_strong_evidence_confirms_after_the_configured_consecutive_count():
    """Scores at least 0.65 use the strong path rather than moderate accumulation."""
    tracker = ContextTracker(hard_confirmations=2)
    tracker.observe(
        ContextObservation(
            goal={"anchor": 1.0},
            entities={"anchor": 1.0},
            sources={"anchor": 1.0},
        )
    )
    candidate = ContextObservation(
        goal={"candidate": 1.0},
        entities={"candidate": 1.0},
        sources={"candidate": 1.0},
    )

    assert tracker.observe(candidate).kind == "soft"
    decision = tracker.observe(candidate)

    assert decision.kind == "hard"
    assert decision.score == pytest.approx(0.75)


def test_configured_confirmation_count_applies_to_moderate_path():
    """A configured count above two must delay otherwise qualifying 0.40 evidence."""
    tracker = ContextTracker(hard_confirmations=3)
    tracker.observe(ContextObservation(goal={"anchor": 1.0}))
    candidate = ContextObservation(goal={"candidate": 1.0})

    assert tracker.observe(candidate).kind == "soft"
    assert tracker.observe(candidate).kind == "soft"
    decision = tracker.observe(candidate)

    assert (decision.kind, decision.confirmations, decision.score) == ("hard", 3, 0.40)


def test_large_weighted_maps_produce_finite_weighted_jaccard_scores():
    """Finite input weights near float limits must not overflow the Jaccard sums."""
    tracker = ContextTracker()
    tracker.observe(ContextObservation(goal={"shared": 1e308, "old": 1e308}))

    decision = tracker.observe(
        ContextObservation(goal={"shared": 1e308, "new": 1e308})
    )

    assert decision.components["goal_divergence"] == pytest.approx(2 / 3)
    assert decision.score == pytest.approx((2 / 3) * 0.40)
    assert all(value < float("inf") for value in decision.components.values())
    assert decision.score < float("inf")


def test_identical_large_weights_remain_zero_divergence():
    """Scaling must preserve the zero distance of identical near-limit maps."""
    tracker = ContextTracker()
    tracker.observe(ContextObservation(goal={"mass": 1e308}))

    decision = tracker.observe(ContextObservation(goal={"mass": 1e308}))

    assert decision.components["goal_divergence"] == 0.0
    assert decision.score == 0.0


def test_combined_score_uses_each_coefficient_and_maxes_participants_tools():
    """All scored components must sum to one when every divergent component is one."""
    tracker = ContextTracker(temporal_gap=timedelta(minutes=1))
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tracker.observe(
        ContextObservation(
            goal={"a": 1.0},
            entities={"a": 1.0},
            participants={"a": 1.0},
            tools={"a": 1.0},
            sources={"a": 1.0},
            observed_at=started,
        )
    )

    decision = tracker.observe(
        ContextObservation(
            goal={"b": 1.0},
            entities={"b": 1.0},
            participants={"b": 1.0},
            tools={"b": 1.0},
            sources={"b": 1.0},
            observed_at=started + timedelta(minutes=2),
        )
    )

    assert decision.components == {
        "goal_divergence": 1.0,
        "entity_turnover": 1.0,
        "participant_turnover": 1.0,
        "tool_turnover": 1.0,
        "source_change": 1.0,
        "temporal_discontinuity": 1.0,
    }
    assert decision.score == 1.0


def test_observation_and_decision_maps_are_defensively_isolated():
    """Later input mutation cannot rewrite history and returned components are read-only."""
    weights = {"anchor": 1.0}
    tracker = ContextTracker()
    tracker.observe(ContextObservation(goal=weights))
    weights.clear()
    weights["candidate"] = 1.0

    decision = tracker.observe(ContextObservation(goal=weights))

    assert decision.components["goal_divergence"] == 1.0
    with pytest.raises(TypeError):
        decision.components["goal_divergence"] = 0.0  # type: ignore[index]


def _strong_observation(tag: str) -> ContextObservation:
    return ContextObservation(
        goal={f"goal:{tag}": 1.0},
        entities={f"entity:{tag}": 1.0},
        sources={f"source:{tag}": 1.0},
    )


def test_fingerprint_lru_retains_distinct_contexts_through_stable_repeats():
    """Refreshing one known fingerprint must not evict any of sixteen distinct contexts."""
    tracker = ContextTracker()
    context_ids = {0: tracker.observe(_strong_observation("0")).context_id}
    for number in range(1, 16):
        tracker.observe(_strong_observation(str(number)))
        context_ids[number] = tracker.observe(_strong_observation(str(number))).context_id

    for _ in range(20):
        tracker.observe(_strong_observation("15"))

    tracker.observe(_strong_observation("0"))
    returned = tracker.observe(_strong_observation("0"))

    assert returned.context_id == context_ids[0]


def test_fingerprint_lru_evicts_the_oldest_distinct_context():
    """Adding a seventeenth distinct context evicts the least recently used fingerprint."""
    tracker = ContextTracker()
    context_ids = {0: tracker.observe(_strong_observation("0")).context_id}
    for number in range(1, 16):
        tracker.observe(_strong_observation(str(number)))
        context_ids[number] = tracker.observe(_strong_observation(str(number))).context_id

    for _ in range(20):
        tracker.observe(_strong_observation("15"))
    tracker.observe(_strong_observation("0"))
    assert tracker.observe(_strong_observation("0")).context_id == context_ids[0]

    tracker.observe(_strong_observation("16"))
    tracker.observe(_strong_observation("16"))
    tracker.observe(_strong_observation("1"))
    returned = tracker.observe(_strong_observation("1"))

    assert returned.context_id != context_ids[1]


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
