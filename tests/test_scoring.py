"""Pure recall scoring shared by recall(), the margin counterfactual, and the replay."""

import pytest

from scoring import DEFAULT_RECENCY_CAP, MODES, score_candidate


def test_modes_are_exactly_tiebreak_and_additive():
    assert MODES == ("tiebreak", "additive")


def test_additive_matches_the_historical_formula():
    s = score_candidate(
        0.8, 0.5, False, mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert s == pytest.approx(0.8 * 0.6 + 0.5 * 0.4)


def test_tiebreak_bounds_recency_by_cap():
    fresh = score_candidate(
        0.8, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    stale = score_candidate(
        0.8, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert fresh - stale == pytest.approx(0.02)


def test_tiebreak_cannot_overturn_a_similarity_gap_wider_than_cap():
    better_old = score_candidate(
        0.84, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    worse_new = score_candidate(
        0.80, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert better_old > worse_new


def test_auto_generated_penalty_applies_in_both_modes():
    for mode in MODES:
        plain = score_candidate(
            0.8, 0.5, False, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02
        )
        auto = score_candidate(
            0.8, 0.5, True, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02
        )
        assert auto == pytest.approx(plain * 0.7)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        score_candidate(
            0.8,
            0.5,
            False,
            mode="sideways",
            w_sim=0.6,
            w_rec=0.4,
            cap=0.02,
        )


def test_default_cap_is_provisional_near_tie_threshold():
    assert DEFAULT_RECENCY_CAP == 0.02
