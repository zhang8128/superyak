"""Tests for tropical margins — recall ranking separation and bias stability."""

import pytest

from margins import margin_stats, stability


def entry(eid, score, similarity=0.8, from_fts=False):
    return {"id": eid, "score": score, "similarity": similarity, "from_fts": from_fts}


class TestMarginStats:
    def test_top_margin_is_gap_between_first_and_second(self):
        stats = margin_stats([
            entry("a", 0.90),
            entry("b", 0.60),
            entry("c", 0.10),
        ])
        assert stats["top"] == pytest.approx(0.30)

    def test_normalized_divides_gap_by_full_spread(self):
        # spread = 0.90 - 0.10 = 0.80, gap = 0.30
        stats = margin_stats([
            entry("a", 0.90),
            entry("b", 0.60),
            entry("c", 0.10),
        ])
        assert stats["normalized"] == pytest.approx(0.375)

    def test_identical_scores_are_a_near_tie_with_zero_margin(self):
        stats = margin_stats([entry("a", 0.5), entry("b", 0.5), entry("c", 0.5)])
        assert stats["top"] == pytest.approx(0.0)
        assert stats["near_tie"] is True
        assert stats["normalized"] == pytest.approx(0.0)

    def test_wide_gap_is_not_a_near_tie(self):
        stats = margin_stats([entry("a", 0.9), entry("b", 0.2)])
        assert stats["near_tie"] is False

    def test_near_tie_threshold_is_configurable(self):
        entries = [entry("a", 0.500), entry("b", 0.495)]
        assert margin_stats(entries, near_tie_threshold=0.01)["near_tie"] is True
        assert margin_stats(entries, near_tie_threshold=0.001)["near_tie"] is False

    def test_single_result_has_no_runner_up(self):
        stats = margin_stats([entry("a", 0.9)])
        assert stats["top"] is None
        assert stats["near_tie"] is False
        assert stats["n"] == 1

    def test_empty_result_set(self):
        stats = margin_stats([])
        assert stats["top"] is None
        assert stats["n"] == 0

    def test_fts_tie_flagged_when_runner_up_came_from_keyword_fallback(self):
        # FTS hits carry a flat similarity — a near-tie against one is an
        # artifact of the fallback, not evidence the store cannot discriminate.
        stats = margin_stats([
            entry("a", 0.500),
            entry("b", 0.495, similarity=0.5, from_fts=True),
        ])
        assert stats["near_tie"] is True
        assert stats["fts_tie"] is True

    def test_fts_tie_not_flagged_for_genuine_vector_near_tie(self):
        stats = margin_stats([
            entry("a", 0.500),
            entry("b", 0.495, similarity=0.82, from_fts=False),
        ])
        assert stats["near_tie"] is True
        assert stats["fts_tie"] is False

    def test_fts_tie_not_flagged_when_margin_is_wide(self):
        stats = margin_stats([
            entry("a", 0.9),
            entry("b", 0.2, similarity=0.5, from_fts=True),
        ])
        assert stats["fts_tie"] is False

    def test_does_not_assume_input_is_sorted(self):
        stats = margin_stats([entry("b", 0.60), entry("a", 0.90), entry("c", 0.10)])
        assert stats["top"] == pytest.approx(0.30)


class TestStability:
    def test_unchecked_when_no_bias_was_applied(self):
        result = stability("a", None, bias_applied=False)
        assert result["checked"] is False
        assert result["survives"] is None
        assert result["displaced"] is None

    def test_survives_when_unbiased_query_picks_the_same_top(self):
        result = stability("a", "a", bias_applied=True)
        assert result["checked"] is True
        assert result["survives"] is True
        assert result["displaced"] is None

    def test_does_not_survive_when_bias_flipped_the_winner(self):
        result = stability("a", "b", bias_applied=True)
        assert result["checked"] is True
        assert result["survives"] is False
        assert result["displaced"] == "b"

    def test_unchecked_when_unbiased_pass_returned_nothing(self):
        result = stability("a", None, bias_applied=True)
        assert result["checked"] is False
        assert result["survives"] is None
