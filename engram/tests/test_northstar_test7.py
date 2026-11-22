"""North-star test 7's pieces: the auditor, the five arms, the scoring, the bootstrap, the readings, and
do-no-harm/ceiling checks -- on hand-made instances and the stub fixture generator. No model, no network,
no real Tardis generator (it doesn't exist yet).

Every number asserted against a hand-made instance below was computed independently by hand (not by
running the code and copying its output) and is reproduced in each test's docstring or an inline comment,
so the arithmetic can be checked without re-deriving it.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from experiments.northstar import test7 as ns
from experiments.northstar import _stub_fixture


# ======================================================================================
# A hand-made instance, used across the auditor, collapse, arm and scoring tests.
#
# K=4 sources (0=bad, 1=copier, 2 and 3 honest), M=6 items, true values all 0, sigma=1.
# truth: biased_items=[0,1], copied_items=[0,2] -> scored_items = [0] (copied AND biased).
#
#   reports[0] (bad)    = [10, 10,  1,  1,  1,  1]
#   reports[1] (copier) = [10,  2,  1,  2,  2,  2]   (copies bad's item0 and item2 exactly, tau=0)
#   reports[2] (honest) = [ 0,  0,  0,  0,  0,  0]
#   reports[3] (honest) = [-2, -2, -2, -2, -2, -2]
#
# Hand-computed pairwise ell (25th percentile of squared differences over all 6 items, no interpolation
# ambiguity since every pair's 6 squared diffs split 2-2-2 into three distinct values, so the 25th
# percentile -- index 1.25 of the sorted 6 -- always lands exactly on the smaller of the two tied-at-rank-1
# values, i.e. the pair's own minimum level):
#   ell(0,1) = 0.25   (diffs^2 = [0, 64, 0, 1, 1, 1])
#   ell(0,2) = 1.0    (diffs^2 = [100,100,1,1,1,1])
#   ell(0,3) = 9.0    (diffs^2 = [144,144,9,9,9,9])
#   ell(1,2) = 4.0    (diffs^2 = [100,4,1,4,4,4])
#   ell(1,3) = 16.0   (diffs^2 = [144,16,9,16,16,16])
#   ell(2,3) = 4.0    (diffs^2 = [4,4,4,4,4,4], constant)
# ell_bar = median([0.25, 1.0, 4.0, 4.0, 9.0, 16.0]) = (4.0 + 4.0) / 2 = 4.0
# r(0,1) = 0.0625, r(0,2) = 0.25, r(0,3) = 2.25, r(1,2) = 1.0, r(1,3) = 4.0, r(2,3) = 1.0
# At theta = 0.1, only (0,1) flags.
# s_hat = sqrt(4.0 / (2*0.1015)) = sqrt(4.0/0.203) = sqrt(19.7044...) = 4.43897...
# ======================================================================================

def _hand_reports() -> np.ndarray:
    return np.array([
        [10.0, 10.0, 1.0, 1.0, 1.0, 1.0],
        [10.0, 2.0, 1.0, 2.0, 2.0, 2.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [-2.0, -2.0, -2.0, -2.0, -2.0, -2.0],
    ])


def _hand_mask() -> np.ndarray:
    return np.ones((4, 6), dtype=bool)


def _hand_chains() -> np.ndarray:
    chains = np.full((4, 6), None, dtype=object)
    chains[1, 0] = 0
    chains[1, 2] = 0
    return chains


def _hand_truth() -> dict:
    return {
        "bad": 0, "copier": 1,
        "biased_items": np.array([0, 1]), "copied_items": np.array([0, 2]),
        "true_values": np.zeros(6), "honest_counts_on_copied": np.array([2, 2]),
    }


# -------------------------------------------------------------------------------------
# The auditor
# -------------------------------------------------------------------------------------

class TestPairwiseLowerQuartile:
    def test_matches_hand_computed_ell_for_every_pair(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        expected = {(0, 1): 0.25, (0, 2): 1.0, (0, 3): 9.0, (1, 2): 4.0, (1, 3): 16.0, (2, 3): 4.0}
        assert ell.keys() == expected.keys()
        for pair, value in expected.items():
            assert ell[pair] == pytest.approx(value)

    def test_a_pair_sharing_fewer_than_min_shared_items_is_not_scored(self):
        reports = _hand_reports()
        mask = _hand_mask().copy()
        mask[2, 3:] = False  # source 2 now shares only 3 items with everyone else
        ell = ns.pairwise_lower_quartile(reports, mask, min_shared=4)
        assert (0, 2) not in ell and (1, 2) not in ell and (2, 3) not in ell
        assert (0, 1) in ell  # sources 0 and 1 still share all 6


class TestEllBarAndRatios:
    def test_ell_bar_is_the_median_over_eligible_pairs(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        assert ns.ell_bar(ell) == pytest.approx(4.0)

    def test_ratios_match_hand_computed_values(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        ratios = ns.pair_ratios(ell)
        expected = {(0, 1): 0.0625, (0, 2): 0.25, (0, 3): 2.25, (1, 2): 1.0, (1, 3): 4.0, (2, 3): 1.0}
        for pair, value in expected.items():
            assert ratios[pair] == pytest.approx(value)

    def test_empty_ell_gives_empty_ratios_and_no_ell_bar(self):
        assert ns.pair_ratios({}) == {}
        assert ns.ell_bar({}) is None


class TestFlaggedPairs:
    def test_only_the_true_copier_pair_flags_at_theta_point_one(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        ratios = ns.pair_ratios(ell)
        assert ns.flagged_pairs(ratios, theta=0.1) == [(0, 1)]

    def test_a_generous_theta_flags_every_pair_under_it(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        ratios = ns.pair_ratios(ell)
        flagged = set(ns.flagged_pairs(ratios, theta=1.5))
        # under 1.5: r(0,1)=0.0625, r(0,2)=0.25, r(1,2)=1.0, r(2,3)=1.0; not under: r(0,3)=2.25, r(1,3)=4.0
        assert flagged == {(0, 1), (0, 2), (1, 2), (2, 3)}


class TestScaleEstimate:
    def test_matches_hand_computed_s_hat(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        s_hat = ns.scale_estimate(ell)
        assert s_hat == pytest.approx(math.sqrt(4.0 / (2 * 0.1015)))

    def test_none_with_no_eligible_pairs(self):
        assert ns.scale_estimate({}) is None


class TestCalibrateTheta:
    def test_returns_a_theta_and_a_false_flag_rate_per_b_s_on_the_stub(self):
        result = ns.calibrate_theta(4, 20, 0.5, _stub_fixture.generate, seed_root=1, n_cal=60)
        assert "theta" in result and np.isfinite(result["theta"])
        assert result["n_valid"] <= 60
        assert result["false_flag_rate"]
        for rate in result["false_flag_rate"].values():
            assert 0.0 <= rate <= 1.0

    def test_deterministic_for_the_same_seed_root(self):
        a = ns.calibrate_theta(4, 20, 0.5, _stub_fixture.generate, seed_root=42, n_cal=40)
        b = ns.calibrate_theta(4, 20, 0.5, _stub_fixture.generate, seed_root=42, n_cal=40)
        assert a["theta"] == b["theta"]


# -------------------------------------------------------------------------------------
# Collapse and the five arms
# -------------------------------------------------------------------------------------

class TestCollapseConsensus:
    def test_naive_matches_hand_computed_medians(self):
        # N: item0 median([10,10,0,-2])=5; item1 median([10,2,0,-2])=1; item2 median([1,1,0,-2])=0.5;
        # items 3,4,5 median([1,2,0,-2])=0.5
        cons = ns.collapse_consensus(_hand_reports(), _hand_mask(), [])
        np.testing.assert_allclose(cons, [5.0, 1.0, 0.5, 0.5, 0.5, 0.5])

    def test_oracle_pair_on_its_items_matches_hand_computed_medians(self):
        # collapse (0,1) on items {0,2} only: item0 -> merged [10, 0, -2] median 0; item2 -> merged
        # [1, 0, -2] median 0; items 1,3,4,5 untouched (same as naive).
        pair_specs = [(0, 1, {0, 2})]
        cons = ns.collapse_consensus(_hand_reports(), _hand_mask(), pair_specs)
        np.testing.assert_allclose(cons, [0.0, 1.0, 0.0, 0.5, 0.5, 0.5])

    def test_inferred_style_collapse_on_every_item_matches_hand_computed_medians(self):
        # collapse (0,1) on every item (items=None): item0->[10,0,-2]=0; item1->merged(10,2)=6,[6,0,-2]=0;
        # item2->[1,0,-2]=0; item3,4,5 -> merged(1,2)=1.5, [1.5,0,-2]=0
        pair_specs = [(0, 1, None)]
        cons = ns.collapse_consensus(_hand_reports(), _hand_mask(), pair_specs)
        np.testing.assert_allclose(cons, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_collapsing_a_pair_uses_the_mean_not_the_sum(self):
        # 3 reporters on one item: i=1, j=3 (mean 2, sum 4), k=3. Collapsing (i,j) leaves exactly two
        # values whose median is their average: with the mean, median([2,3])=2.5; with the sum (a wrong
        # collapse), median([4,3])=3.5 -- a different number, so this is sensitive to the bug.
        reports = np.array([[1.0], [3.0], [3.0]])
        mask = np.ones((3, 1), dtype=bool)
        cons = ns.collapse_consensus(reports, mask, [(0, 1, None)])
        assert cons[0] == pytest.approx(2.5)

    def test_a_source_is_collapsed_into_at_most_one_pair_per_item(self):
        # overlapping specs sharing source 0: only the first spec that both members are free for wins.
        reports = _hand_reports()
        mask = _hand_mask()
        pair_specs = [(0, 1, {0}), (0, 2, {0})]
        cons = ns.collapse_consensus(reports, mask, pair_specs)
        # (0,1) collapses on item0 -> merged 10, remaining [0,-2] -> median([10,0,-2]) = 0; (0,2) never
        # applies to item0 since 0 is already used.
        assert cons[0] == 0.0


class TestRestsOnDependentReports:
    def test_pins_item_level_flags_against_the_oracle_collapse(self):
        # with_collapse = oracle's consensus [0, 1, 0, 0.5, 0.5, 0.5]; without_collapse = naive
        # [5, 1, 0.5, 0.5, 0.5, 0.5]. diffs = [5, 0, 0.5, 0, 0, 0]. 0.5*s_hat = 0.5*4.43897 = 2.2195.
        # So only item0 (diff 5) exceeds it; item2's diff of 0.5 does not.
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        s_hat = ns.scale_estimate(ell)
        pair_specs = [(0, 1, {0, 2})]
        flags = ns.rests_on_dependent_reports(_hand_reports(), _hand_mask(), pair_specs, s_hat)
        np.testing.assert_array_equal(flags, [True, False, False, False, False, False])

    def test_false_everywhere_with_no_pair_specs_or_no_scale(self):
        flags = ns.rests_on_dependent_reports(_hand_reports(), _hand_mask(), [], 4.0)
        assert not flags.any()
        flags = ns.rests_on_dependent_reports(_hand_reports(), _hand_mask(), [(0, 1, {0})], None)
        assert not flags.any()


class TestArmNaive:
    def test_matches_collapse_with_no_pairs(self):
        np.testing.assert_allclose(
            ns.arm_naive(_hand_reports(), _hand_mask()),
            ns.collapse_consensus(_hand_reports(), _hand_mask(), []))


class TestProvenancePairs:
    def test_groups_a_named_chain_into_one_pair_with_every_item_it_names(self):
        pairs = ns.provenance_pairs(_hand_chains())
        assert pairs == [(0, 1, {0, 2})]

    def test_empty_chains_give_no_pairs(self):
        assert ns.provenance_pairs(np.full((4, 6), None, dtype=object)) == []

    def test_orders_each_pair_with_the_smaller_index_first(self):
        chains = np.full((3, 2), None, dtype=object)
        chains[0, 0] = 2  # source 0 names source 2 -> pair should be (0, 2), not (2, 0)
        assert ns.provenance_pairs(chains) == [(0, 2, {0})]


class TestArmProvenance:
    def test_matches_the_oracle_on_the_hand_made_instance(self):
        # chains name (0,1) on exactly {0,2}, the same items copied_items names -> P equals O here.
        p = ns.arm_provenance(_hand_reports(), _hand_mask(), _hand_chains())
        o = ns.arm_oracle(_hand_reports(), _hand_mask(), 0, 1, np.array([0, 2]))
        np.testing.assert_allclose(p, o)
        np.testing.assert_allclose(p, [0.0, 1.0, 0.0, 0.5, 0.5, 0.5])


class TestPHalf:
    def test_drops_exactly_ceil_n_over_2_copied_items_chain(self):
        rng = np.random.default_rng(0)
        copied_items = np.array([0, 2, 5, 7])  # n=4, ceil(4/2)=2 should drop
        chains = np.full((4, 10), None, dtype=object)
        for item in copied_items:
            chains[1, item] = 0
        pairs = ns.p_half_pairs(chains, copied_items, rng)
        assert len(pairs) == 1
        kept_items = pairs[0][2]
        assert len(kept_items) == 2
        assert kept_items <= set(copied_items.tolist())

    def test_odd_n_drops_the_ceiling(self):
        rng = np.random.default_rng(0)
        copied_items = np.array([0, 2, 5])  # n=3, ceil(3/2)=2
        chains = np.full((4, 10), None, dtype=object)
        for item in copied_items:
            chains[1, item] = 0
        pairs = ns.p_half_pairs(chains, copied_items, rng)
        assert len(pairs[0][2]) == 1

    def test_dropping_every_copied_item_leaves_no_pair_at_all(self):
        rng = np.random.default_rng(0)
        copied_items = np.array([0])  # n=1, ceil(1/2)=1 -> drops the only one
        chains = np.full((4, 10), None, dtype=object)
        chains[1, 0] = 0
        pairs = ns.p_half_pairs(chains, copied_items, rng)
        assert pairs == []


class TestPHalfDropSeed:
    def test_deterministic_for_the_same_instance(self):
        cell = {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.25}
        a = ns.p_half_drop_seed(cell, 3, 99).integers(0, 1_000_000, size=5)
        b = ns.p_half_drop_seed(cell, 3, 99).integers(0, 1_000_000, size=5)
        np.testing.assert_array_equal(a, b)

    def test_differs_across_instances(self):
        cell = {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.25}
        a = ns.p_half_drop_seed(cell, 3, 99).integers(0, 1_000_000, size=5)
        b = ns.p_half_drop_seed(cell, 4, 99).integers(0, 1_000_000, size=5)
        assert not np.array_equal(a, b)


class TestArmInferred:
    def test_flags_the_true_copier_pair_and_matches_hand_computed_consensus(self):
        cons, flagged, ell, s_hat = ns.arm_inferred(_hand_reports(), _hand_mask(), theta=0.1)
        assert flagged == [(0, 1)]
        np.testing.assert_allclose(cons, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        assert s_hat == pytest.approx(math.sqrt(4.0 / 0.203))

    def test_a_theta_of_zero_flags_nothing(self):
        cons, flagged, ell, s_hat = ns.arm_inferred(_hand_reports(), _hand_mask(), theta=0.0)
        assert flagged == []
        np.testing.assert_allclose(cons, ns.arm_naive(_hand_reports(), _hand_mask()))


class TestArmOracle:
    def test_matches_hand_computed_consensus(self):
        cons = ns.arm_oracle(_hand_reports(), _hand_mask(), 0, 1, np.array([0, 2]))
        np.testing.assert_allclose(cons, [0.0, 1.0, 0.0, 0.5, 0.5, 0.5])

    def test_no_copier_collapses_nothing(self):
        cons = ns.arm_oracle(_hand_reports(), _hand_mask(), 0, None, np.array([]))
        np.testing.assert_allclose(cons, ns.arm_naive(_hand_reports(), _hand_mask()))

    def test_no_copied_items_collapses_nothing(self):
        cons = ns.arm_oracle(_hand_reports(), _hand_mask(), 0, 1, np.array([], dtype=int))
        np.testing.assert_allclose(cons, ns.arm_naive(_hand_reports(), _hand_mask()))


# -------------------------------------------------------------------------------------
# Scoring
# -------------------------------------------------------------------------------------

class TestScoredItems:
    def test_is_the_intersection_of_copied_and_biased_items(self):
        # the spec's own pin: "the scored items are copied AND biased"
        truth = _hand_truth()
        np.testing.assert_array_equal(ns.scored_items(truth), [0])

    def test_empty_when_nothing_is_both(self):
        truth = {"biased_items": np.array([1, 3]), "copied_items": np.array([0, 2])}
        assert len(ns.scored_items(truth)) == 0


class TestConsensusError:
    def test_is_mean_absolute_deviation_over_sigma(self):
        consensus = np.array([0.0, 2.0, 4.0])
        true_values = np.array([0.0, 0.0, 0.0])
        err = ns.consensus_error(consensus, true_values, sigma=2.0, items=np.array([1, 2]))
        # |2-0|/2=1, |4-0|/2=2, mean=1.5
        assert err == pytest.approx(1.5)

    def test_nan_with_no_scored_items(self):
        err = ns.consensus_error(np.zeros(3), np.zeros(3), 1.0, np.array([], dtype=int))
        assert math.isnan(err)

    def test_on_the_hand_made_instance_n_vs_o_vs_p_vs_i(self):
        reports, mask, truth, chains = _hand_reports(), _hand_mask(), _hand_truth(), _hand_chains()
        scored = ns.scored_items(truth)
        cons_n = ns.arm_naive(reports, mask)
        cons_o = ns.arm_oracle(reports, mask, truth["bad"], truth["copier"], truth["copied_items"])
        cons_p = ns.arm_provenance(reports, mask, chains)
        cons_i, _, _, _ = ns.arm_inferred(reports, mask, theta=0.1)
        err_n = ns.consensus_error(cons_n, truth["true_values"], 1.0, scored)
        err_o = ns.consensus_error(cons_o, truth["true_values"], 1.0, scored)
        err_p = ns.consensus_error(cons_p, truth["true_values"], 1.0, scored)
        err_i = ns.consensus_error(cons_i, truth["true_values"], 1.0, scored)
        assert err_n == pytest.approx(5.0)
        assert err_o == pytest.approx(0.0)
        assert err_p == pytest.approx(0.0)
        assert err_i == pytest.approx(0.0)


class TestPooledGain:
    def test_weighs_every_cell_equally_not_by_instance_count(self):
        # cell "a" has 1 instance at 10.0; cell "b" has 3 instances averaging 0.0 -> equal-cell mean is
        # (10.0 + 0.0)/2 = 5.0, not the instance-weighted (10 + 0 + 0 + 0)/4 = 2.5.
        pooled = ns.pooled_gain({"a": [10.0], "b": [0.0, 0.0, 0.0]})
        assert pooled == pytest.approx(5.0)

    def test_drops_nan_and_empty_cells(self):
        pooled = ns.pooled_gain({"a": [1.0, float("nan")], "b": [], "c": [3.0]})
        assert pooled == pytest.approx(2.0)  # mean([1.0]) and mean([3.0]) -> mean([1.0, 3.0]) = 2.0

    def test_all_nan_gives_nan(self):
        assert math.isnan(ns.pooled_gain({"a": [float("nan")]}))


class TestSIRatio:
    def test_is_pooled_numerator_over_pooled_denominator(self):
        ratio = ns.s_i_ratio({"a": [2.0]}, {"a": [4.0]})
        assert ratio == pytest.approx(0.5)

    def test_weighs_cells_equally_in_both_numerator_and_denominator(self):
        num = {"a": [10.0], "b": [0.0, 0.0]}  # pooled = 5.0
        den = {"a": [10.0], "b": [10.0, 10.0]}  # pooled = 10.0
        assert ns.s_i_ratio(num, den) == pytest.approx(0.5)


class TestPerCellRatios:
    def test_omits_a_cell_whose_denominator_is_under_the_floor(self):
        num = {"thin": [1.0], "thick": [1.0]}
        den = {"thin": [0.01], "thick": [1.0]}
        out = ns.per_cell_ratios(num, den, floor=0.1)
        assert "thin" not in out
        assert out["thick"] == pytest.approx(1.0)


# -------------------------------------------------------------------------------------
# The bootstrap and readings
#
# Constant-valued cells make the bootstrap's resampling a no-op (every resample of a constant array has
# the same mean), so the point estimate and the whole 95% interval collapse to one exact number -- a way to
# pin the bootstrap's arithmetic without depending on its random draws.
# -------------------------------------------------------------------------------------

class TestBootstrapRatioCi:
    def test_constant_cells_give_a_point_interval_at_the_true_ratio(self):
        num = {"a": [0.9, 0.9, 0.9], "b": [0.9, 0.9]}
        den = {"a": [1.0, 1.0, 1.0], "b": [1.0, 1.0]}
        result = ns.bootstrap_ratio_ci(num, den, replicates=200)
        assert result["point"] == pytest.approx(0.9)
        assert result["ci95"][0] == pytest.approx(0.9)
        assert result["ci95"][1] == pytest.approx(0.9)

    def test_is_deterministic_for_the_fixed_seed(self):
        num = {"a": [1.0, 2.0, 3.0, 0.5]}
        den = {"a": [2.0, 2.0, 2.0, 2.0]}
        a = ns.bootstrap_ratio_ci(num, den, replicates=500, seed=ns.BOOTSTRAP_SEED)
        b = ns.bootstrap_ratio_ci(num, den, replicates=500, seed=ns.BOOTSTRAP_SEED)
        assert a == b

    def test_varying_data_gives_a_nondegenerate_interval(self):
        num = {"a": list(np.linspace(0.0, 2.0, 30))}
        den = {"a": [1.0] * 30}
        result = ns.bootstrap_ratio_ci(num, den, replicates=500)
        assert result["ci95"][1] > result["ci95"][0]

    def test_the_spec_s_replicate_count_and_seed_are_the_defaults(self):
        assert ns.BOOTSTRAP_REPLICATES == 10_000
        assert ns.BOOTSTRAP_SEED == 2026112207


class TestPrimaryReading:
    def test_lower_end_at_or_above_point_eight_substitutes_for_the_record(self):
        assert ns.primary_reading([0.8, 0.95]) == "inference substitutes for the record"
        assert ns.primary_reading([0.81, 1.2]) == "inference substitutes for the record"

    def test_upper_end_under_point_five_cannot_be_replaced(self):
        assert ns.primary_reading([0.1, 0.49]) == "the record can't be replaced by this inference"

    def test_otherwise_recovers_part(self):
        assert ns.primary_reading([0.3, 0.6]) == "inference recovers part"
        assert ns.primary_reading([0.5, 0.79]) == "inference recovers part"

    def test_boundary_values_are_exact(self):
        assert ns.primary_reading([0.5, 0.5]) == "inference recovers part"  # upper is not < 0.5
        assert ns.primary_reading([0.79, 0.8]) == "inference recovers part"  # lower is not >= 0.8


class TestDoNoHarm:
    def test_within_band_when_every_resample_is_inside_it(self):
        gains = {"a": [0.01, -0.01, 0.02], "b": [0.0, 0.03]}
        result = ns.do_no_harm(gains, band=0.05)
        assert result["within_band"] is True

    def test_outside_band_when_the_whole_interval_exceeds_it(self):
        gains = {"a": [0.2, 0.2, 0.2], "b": [0.2, 0.2]}  # constant: point and CI are exactly 0.2
        result = ns.do_no_harm(gains, band=0.05)
        assert result["within_band"] is False
        assert result["ci95"][0] == pytest.approx(0.2)


class TestCeilingCheck:
    def test_stops_when_pooled_gain_is_under_the_floor(self):
        result = ns.ceiling_check({"a": [0.05, 0.05]}, floor=0.1)
        assert result["stop"] is True
        assert result["pooled_gain_n_minus_o"] == pytest.approx(0.05)

    def test_does_not_stop_at_or_above_the_floor(self):
        result = ns.ceiling_check({"a": [0.1, 0.1]}, floor=0.1)
        assert result["stop"] is False

    def test_nan_pooled_gain_does_not_stop(self):
        result = ns.ceiling_check({})
        assert result["stop"] is False


# -------------------------------------------------------------------------------------
# Secondary measures
# -------------------------------------------------------------------------------------

class TestGapDelta:
    def test_pairs_i_on_d_against_p_on_c_by_position_within_a_cell(self):
        result = ns.gap_delta({"a": [1.0, 1.0]}, {"a": [0.4, 0.4]})
        assert result["point"] == pytest.approx(0.6)


class TestDetectionRates:
    def test_rates_match_hand_counted_rows(self):
        rows = [
            {"flagged": [[0, 1]], "true_pair": [0, 1]},                 # copier flagged, no honest flag
            {"flagged": [[0, 1], [2, 3]], "true_pair": [0, 1]},         # copier flagged, one honest flag
            {"flagged": [[2, 3]], "true_pair": [0, 1]},                 # copier NOT flagged, one honest flag
            {"flagged": [], "true_pair": [0, 1]},                       # nothing flagged
        ]
        rates = ns.detection_rates(rows)
        assert rates["copier_pair_flagged_rate"] == pytest.approx(0.5)      # 2 of 4
        assert rates["honest_pair_flagged_rate"] == pytest.approx(0.5)      # 2 of 4
        assert rates["mean_honest_pairs_flagged_when_any"] == pytest.approx(1.0)  # one honest pair each time


class TestFalseFlagRateA:
    def test_is_the_share_of_instances_with_any_flag(self):
        rows = [{"flagged": [[0, 1]]}, {"flagged": []}, {"flagged": [[1, 2]]}, {"flagged": []}]
        assert ns.false_flag_rate_a(rows) == pytest.approx(0.5)


class TestBlame:
    def test_scores_are_mean_absolute_deviation_from_consensus(self):
        reports = np.array([[0.0, 2.0], [0.0, 0.0], [10.0, 10.0]])
        mask = np.ones((3, 2), dtype=bool)
        consensus = np.array([0.0, 0.0])
        scores = ns.blame_scores(reports, mask, consensus)
        np.testing.assert_allclose(scores, [1.0, 0.0, 10.0])

    def test_the_most_deviant_source_gets_full_first_credit_with_no_tie(self):
        scores = np.array([1.0, 0.0, 10.0])
        assert ns.blame_first_credit(scores, target=2) == pytest.approx(1.0)
        assert ns.blame_first_credit(scores, target=0) == pytest.approx(0.0)

    def test_a_tie_for_first_splits_credit(self):
        scores = np.array([10.0, 10.0, 1.0])
        assert ns.blame_first_credit(scores, target=0) == pytest.approx(0.5)
        assert ns.blame_first_credit(scores, target=1) == pytest.approx(0.5)
        assert ns.blame_first_credit(scores, target=2) == pytest.approx(0.0)


# -------------------------------------------------------------------------------------
# The stub fixture
# -------------------------------------------------------------------------------------

class TestStubFixtureMinimumsAndShape:
    def test_every_item_has_at_least_two_reports_and_every_source_at_least_five(self):
        cell = {"K": 4, "M": 10, "rho": 0.1, "b": 2.0, "s": 0.5}
        inst = _stub_fixture.generate(cell, "A", 0, seed_root=1)
        mask = ~np.isnan(inst["reports"])
        assert (mask.sum(axis=0) >= 2).all()
        assert (mask.sum(axis=1) >= 5).all()

    def test_reports_and_truth_shapes_match_the_cell(self):
        cell = {"K": 5, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5}
        inst = _stub_fixture.generate(cell, "A", 0, seed_root=1)
        assert inst["reports"].shape == (5, 20)
        assert inst["chains"].shape == (5, 20)
        assert len(inst["truth"]["true_values"]) == 20
        assert inst["truth"]["copier"] is None
        assert len(inst["truth"]["copied_items"]) == 0

    def test_at_least_one_biased_item_even_at_a_tiny_share(self):
        cell = {"K": 4, "M": 20, "rho": 0.9, "b": 2.0, "s": 0.01}
        inst = _stub_fixture.generate(cell, "A", 0, seed_root=1)
        assert len(inst["truth"]["biased_items"]) >= 1


class TestStubFixtureCAndD:
    def test_c_and_d_have_identical_reports(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.25}
        c = _stub_fixture.generate(cell, "C", 7, seed_root=5)
        d = _stub_fixture.generate(cell, "D", 7, seed_root=5)
        np.testing.assert_array_equal(c["reports"], d["reports"])
        np.testing.assert_array_equal(c["truth"]["copied_items"], d["truth"]["copied_items"])
        assert c["truth"]["copier"] == d["truth"]["copier"]

    def test_chains_are_named_only_in_c(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.25}
        c = _stub_fixture.generate(cell, "C", 7, seed_root=5)
        d = _stub_fixture.generate(cell, "D", 7, seed_root=5)
        assert any(entry is not None for entry in c["chains"].flat)
        assert all(entry is None for entry in d["chains"].flat)

    def test_every_chain_entry_names_the_bad_source(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.25}
        c = _stub_fixture.generate(cell, "C", 7, seed_root=5)
        named = [v for v in c["chains"].flat if v is not None]
        assert named and all(v == c["truth"]["bad"] for v in named)

    def test_a_rejects_an_unknown_condition(self):
        with pytest.raises(ValueError):
            _stub_fixture.generate({"K": 4, "M": 10, "rho": 0.5, "b": 2.0, "s": 0.5}, "Z", 0, 1)


# -------------------------------------------------------------------------------------
# The two pinned identities, run against the stub generator (a real instance, not hand-made, since the
# identity must hold for whatever the generator draws -- that's the point of "by construction").
# -------------------------------------------------------------------------------------

class TestPOnCEqualsOracle:
    def test_p_equals_o_exactly_across_many_stub_instances(self):
        cell = {"K": 5, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        for i in range(15):
            inst = _stub_fixture.generate(cell, "C", i, seed_root=11)
            mask = ~np.isnan(inst["reports"])
            truth = inst["truth"]
            p = ns.arm_provenance(inst["reports"], mask, inst["chains"])
            o = ns.arm_oracle(inst["reports"], mask, truth["bad"], truth["copier"], truth["copied_items"])
            np.testing.assert_allclose(p, o, equal_nan=True)


class TestCAndDGiveIdenticalN:
    def test_naive_consensus_is_identical_between_c_and_d_across_many_instances(self):
        cell = {"K": 5, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 1.0, "q": 0.25}
        for i in range(15):
            c = _stub_fixture.generate(cell, "C", i, seed_root=13)
            d = _stub_fixture.generate(cell, "D", i, seed_root=13)
            mask_c = ~np.isnan(c["reports"])
            mask_d = ~np.isnan(d["reports"])
            n_c = ns.arm_naive(c["reports"], mask_c)
            n_d = ns.arm_naive(d["reports"], mask_d)
            np.testing.assert_allclose(n_c, n_d, equal_nan=True)


# -------------------------------------------------------------------------------------
# Orchestration: build_plan, run_cell/run_plan, summarize -- a tiny grid on the stub.
# -------------------------------------------------------------------------------------

class TestRunCell:
    def test_a_cell_rows_carry_every_arm_s_error(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        rows = ns.run_cell(cell, "D", _stub_fixture.generate, seed_root=21, theta=0.1, n_instances=5)
        assert len(rows) == 5
        for row in rows:
            for arm in ("N", "I", "P", "P_half", "O"):
                assert arm in row["consensus_error"]

    def test_an_a_cell_has_no_copy_specific_fields(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5}
        rows = ns.run_cell(cell, "A", _stub_fixture.generate, seed_root=21, theta=0.1, n_instances=3)
        for row in rows:
            assert "O" not in row["consensus_error"]
            assert row["true_pair"] is None


class TestBuildPlanAndRunPlan:
    def _tiny_cells(self):
        return [
            {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5},
            {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.5},
        ]

    def test_build_plan_calibrates_a_and_counts_the_ceiling_for_c_d(self):
        plan = ns.build_plan(
            self._tiny_cells(), generator=_stub_fixture.generate,
            seed_root_calibration=1, seed_root_pilot=2, seed_root_run=3, n_cal=40, n_pilot=20, n_instances=10)
        assert plan["calibrations"]
        assert plan["ceiling"]
        for entry in plan["calibrations"].values():
            assert np.isfinite(entry["theta"])
        for entry in plan["ceiling"].values():
            assert "pooled_gain_n_minus_o" in entry

    def test_run_plan_and_summarize_end_to_end_on_the_stub(self):
        plan = ns.build_plan(
            self._tiny_cells(), generator=_stub_fixture.generate,
            seed_root_calibration=1, seed_root_pilot=2, seed_root_run=3, n_cal=40, n_pilot=20, n_instances=8)
        results = ns.run_plan(plan, generator=_stub_fixture.generate)
        summary = ns.summarize(plan, results)
        assert summary["primary"]["reading"] in (
            "inference substitutes for the record", "the record can't be replaced by this inference",
            "inference recovers part")
        assert "pooled_gain_n_minus_o" in summary["ceiling"]
        assert summary["checks"]["n_identical_between_c_and_d"] is True
        assert summary["checks"]["p_on_c_equals_o_max_abs_diff"] == pytest.approx(0.0, abs=1e-9)


# -------------------------------------------------------------------------------------
# A tiny end-to-end CLI smoke, against the stub generator (labelled as such): 2 cells, 20 instances, just
# to show the plan -> run -> rescore pipe works. Not a real run -- no plan file is committed.
# -------------------------------------------------------------------------------------

class TestCliSmokeEndToEnd:
    def test_plan_run_rescore_round_trip(self, tmp_path):
        cells_path = tmp_path / "cells.json"
        cells_path.write_text(json.dumps([
            {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5},
            {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.5},
        ]))
        plan_path = tmp_path / "plan.json"
        results_path = tmp_path / "results.json"
        engram_root = str(Path(ns.__file__).resolve().parents[2])
        module_args = [sys.executable, "-m", "experiments.northstar.test7"]

        plan_proc = subprocess.run(
            module_args + ["plan", "--cells", str(cells_path), "--out", str(plan_path),
                          "--n-cal", "40", "--n-pilot", "20", "--n-instances", "20"],
            cwd=engram_root, capture_output=True, text=True)
        assert plan_proc.returncode == 0, plan_proc.stderr
        assert plan_path.exists()

        run_proc = subprocess.run(
            module_args + ["run", "--plan", str(plan_path), "--out", str(results_path)],
            cwd=engram_root, capture_output=True, text=True)
        assert run_proc.returncode == 0, run_proc.stderr
        assert results_path.exists()

        rescore_proc = subprocess.run(
            module_args + ["rescore", "--plan", str(plan_path), "--results", str(results_path)],
            cwd=engram_root, capture_output=True, text=True)
        assert rescore_proc.returncode == 0, rescore_proc.stderr
        summary = json.loads(rescore_proc.stdout)
        assert "primary" in summary and "reading" in summary["primary"]
