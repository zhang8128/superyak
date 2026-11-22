"""North-star test 7's pieces: the auditor, the five arms, the scoring, the bootstrap, the readings, the
pilots/cut and do-no-harm/ceiling checks -- on hand-made instances and Tardis's real graded-blame fixture
generator (``experiments.northstar.graded_fixture``, merged 867614fa). No model, no network.

The fixture's own contract (minimums, C/D-identical-reports, chains-only-in-C, and so on) is covered by
``tests/test_northstar_graded_fixture.py``; this file only re-uses the real generator for test7's own
integration-style checks (the P-on-C-equals-O and C-and-D-identical-N identities, run_cell/build_plan), not
its contract.

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
from experiments.northstar import graded_fixture


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

    def test_flagged_pairs_are_ordered_by_increasing_r(self):
        # r(0,1)=0.0625 < r(0,2)=0.25 < r(1,2)=1.0 < r(2,3)=1.0 (a tie, stable on ratios.items() order)
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        ratios = ns.pair_ratios(ell)
        flagged = ns.flagged_pairs(ratios, theta=1.5)
        rs = [ratios[p] for p in flagged]
        assert rs == sorted(rs)

    def test_an_overlapping_pair_with_the_larger_r_is_skipped_when_collapsed_in_order(self):
        # Three pairs all share source 1: (0,1) r=0.3, (1,2) r=0.1, (1,3) r=0.2 -- written here in
        # combination order (0,1) then (1,2) then (1,3), the *wrong* merge order the bug would use.
        # Sorted by increasing r, (1,2) (the smallest r) must merge first, claiming sources 1 and 2, so
        # (0,1) and (1,3) are both skipped.
        ratios = {(0, 1): 0.3, (1, 2): 0.1, (1, 3): 0.2, (0, 2): 5.0}
        flagged = ns.flagged_pairs(ratios, theta=1.0)
        assert flagged == [(1, 2), (1, 3), (0, 1)]

        reports = np.array([[10.0], [0.0], [4.0], [100.0]])  # sources 0,1,2,3 on one item
        mask = np.ones((4, 1), dtype=bool)
        pair_specs = [(p[0], p[1], None) for p in flagged]
        cons = ns.collapse_consensus(reports, mask, pair_specs)
        # (1,2) merges first: (0+4)/2=2; remaining [10, 100] -> median([2,10,100]) = 10. Collapsing (0,1)
        # first instead (the bug) would give (10+0)/2=5; remaining [4,100] -> median([5,4,100]) = 5.
        assert cons[0] == pytest.approx(10.0)


class TestScaleEstimate:
    def test_matches_hand_computed_s_hat(self):
        ell = ns.pairwise_lower_quartile(_hand_reports(), _hand_mask())
        s_hat = ns.scale_estimate(ell)
        assert s_hat == pytest.approx(math.sqrt(4.0 / (2 * 0.1015)))

    def test_none_with_no_eligible_pairs(self):
        assert ns.scale_estimate({}) is None


class TestCalibrateTheta:
    def test_returns_a_theta_and_a_false_flag_rate_per_b_s_on_the_stub(self):
        result = ns.calibrate_theta(4, 20, 0.5, graded_fixture.generate, seed_root=1, n_cal=60)
        assert "theta" in result and np.isfinite(result["theta"])
        assert result["n_valid"] <= 60
        assert result["false_flag_rate"]
        for rate in result["false_flag_rate"].values():
            assert 0.0 <= rate <= 1.0

    def test_deterministic_for_the_same_seed_root(self):
        a = ns.calibrate_theta(4, 20, 0.5, graded_fixture.generate, seed_root=42, n_cal=40)
        b = ns.calibrate_theta(4, 20, 0.5, graded_fixture.generate, seed_root=42, n_cal=40)
        assert a["theta"] == b["theta"]

    def test_the_six_b_s_combinations_get_exactly_equal_counts_when_n_cal_divides_evenly(self):
        # n_cal=600 divides evenly by 6 combinations (3 b's x 2 s's): each must get exactly 100, not
        # whatever an independent per-instance random draw happens to land on.
        result = ns.calibrate_theta(4, 20, 0.5, graded_fixture.generate, seed_root=7, n_cal=600)
        combos = [(b, s) for b in ns.GRID_B for s in ns.GRID_S]
        assert set(result["n_per_bs"]) == {f"b{b}_s{s}" for b, s in combos}
        assert all(n == 100 for n in result["n_per_bs"].values())

    def test_every_combo_is_represented_even_with_few_calibration_instances(self):
        # a purely random per-instance draw over 24 instances could easily miss one of 6 combos; cycling
        # through them never does.
        result = ns.calibrate_theta(4, 20, 0.5, graded_fixture.generate, seed_root=9, n_cal=24)
        assert len(result["n_per_bs"]) == len(ns.GRID_B) * len(ns.GRID_S)
        assert all(n == 4 for n in result["n_per_bs"].values())


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


class TestChainNamedItems:
    def test_is_every_item_any_chain_names_at_all(self):
        np.testing.assert_array_equal(ns.chain_named_items(_hand_chains()), [0, 2])

    def test_empty_chains_give_an_empty_array(self):
        assert len(ns.chain_named_items(np.full((4, 6), None, dtype=object))) == 0

    def test_never_reads_truth_only_chains(self):
        # a chain naming items {1, 5}, disjoint from whatever truth["copied_items"] might say -- the
        # function must report what the chain itself names, not truth's own set.
        chains = np.full((3, 10), None, dtype=object)
        chains[1, 1] = 0
        chains[1, 5] = 0
        np.testing.assert_array_equal(ns.chain_named_items(chains), [1, 5])


class TestIndependentReportCounts:
    def test_with_no_collapse_every_item_counts_its_own_reporters(self):
        mask = np.array([[True, True], [True, False], [True, True]])
        counts = ns.independent_report_counts(mask, [])
        np.testing.assert_array_equal(counts, [3, 2])

    def test_a_collapsed_pair_counts_once_not_twice_on_its_items(self):
        mask = np.ones((4, 2), dtype=bool)
        # pair (0,1) collapses on item 0 only; item 1 is untouched.
        counts = ns.independent_report_counts(mask, [(0, 1, {0})])
        np.testing.assert_array_equal(counts, [3, 4])  # item0: 4 reporters - 2 used + 1 merged = 3

    def test_a_pair_missing_from_an_item_s_reporters_does_not_collapse_there(self):
        mask = np.array([[True, False], [True, True], [True, True]])  # source 0 doesn't report item 1
        counts = ns.independent_report_counts(mask, [(0, 1, None)])
        assert counts[0] == 2  # item0: sources 0,1 collapse -> 3 reporters - 2 used + 1 = 2
        assert counts[1] == 2  # item1: source 0 absent, pair never applies -> both of 1,2 count normally


class TestPopulationComposition:
    def test_counts_sum_to_the_population_size_per_axis(self):
        cells = [
            {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.25, "tau": 0.5, "q": 0.25},
            {"K": 4, "M": 20, "rho": 0.5, "b": 4.0, "s": 0.5, "tau": 1.0, "q": 0.5},
            {"K": 6, "M": 60, "rho": 0.9, "b": 8.0, "s": 0.5, "tau": 1.5, "q": 0.5},
        ]
        composition = ns.population_composition(cells, axes=("K", "b", "s", "tau", "q"))
        for axis in ("K", "b", "s", "tau", "q"):
            assert sum(composition[axis].values()) == len(cells)

    def test_axes_without_the_key_are_skipped_not_zero_filled(self):
        cells = [{"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5}]  # no tau/q (an A cell)
        composition = ns.population_composition(cells, axes=("K", "b", "s", "tau", "q"))
        assert "tau" not in composition and "q" not in composition
        assert composition["K"] == {"4": 1}

    def test_empty_population_gives_an_empty_composition(self):
        assert ns.population_composition([]) == {}


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

    def test_a_zero_pooled_denominator_gives_nan_not_a_raised_zerodivisionerror(self):
        # plain Python float division by an exact 0.0 raises ZeroDivisionError, unlike numpy's; pooled_gain
        # returns plain floats, so s_i_ratio must guard this itself.
        assert math.isnan(ns.s_i_ratio({"a": [1.0]}, {"a": [0.0]}))


class TestSafeRatio:
    def test_zero_denominator_gives_nan(self):
        assert math.isnan(ns.safe_ratio(1.0, 0.0))

    def test_non_finite_either_side_gives_nan(self):
        assert math.isnan(ns.safe_ratio(float("nan"), 1.0))
        assert math.isnan(ns.safe_ratio(1.0, float("inf")))

    def test_ordinary_division_is_unaffected(self):
        assert ns.safe_ratio(3.0, 2.0) == pytest.approx(1.5)


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


class TestBootstrapPooledMeanCi:
    def test_result_does_not_depend_on_the_input_dict_s_insertion_order(self):
        # the same data, inserted in two different key orders, must give the same replicate sequence (and
        # so the same CI) for a fixed seed -- the bootstrap's own cell order must come from sorting the
        # keys, never from whatever order the caller happened to build the dict in.
        forward = {"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0], "c": [6.0]}
        backward = {"c": [6.0], "b": [4.0, 5.0], "a": [1.0, 2.0, 3.0]}
        result_forward = ns.bootstrap_pooled_mean_ci(forward, replicates=300)
        result_backward = ns.bootstrap_pooled_mean_ci(backward, replicates=300)
        assert result_forward == result_backward


class TestBootstrapSIAndSPHalf:
    def test_paired_bootstrap_matches_independent_point_estimates(self):
        n_i = {"a": [2.0, 3.0]}
        o_d = {"a": [4.0, 4.0]}
        n_half = {"a": [1.0, 1.0]}
        o_c = {"a": [4.0, 4.0]}
        result = ns.bootstrap_s_i_and_s_phalf(n_i, o_d, n_half, o_c, replicates=200)
        assert result["s_i"]["point"] == pytest.approx(ns.s_i_ratio(n_i, o_d))
        assert result["s_p_half"]["point"] == pytest.approx(ns.s_i_ratio(n_half, o_c))

    def test_constant_cells_give_degenerate_intervals_at_the_true_ratios(self):
        n_i = {"a": [1.0, 1.0, 1.0]}
        o_d = {"a": [2.0, 2.0, 2.0]}
        n_half = {"a": [0.5, 0.5, 0.5]}
        o_c = {"a": [2.0, 2.0, 2.0]}
        result = ns.bootstrap_s_i_and_s_phalf(n_i, o_d, n_half, o_c, replicates=200)
        assert result["s_i"]["ci95"] == [pytest.approx(0.5), pytest.approx(0.5)]
        assert result["s_p_half"]["ci95"] == [pytest.approx(0.25), pytest.approx(0.25)]

    def test_the_two_ratios_share_one_resample_per_cell_per_replicate(self):
        # n_half is exactly 2*n_i, and o_c equals o_d, so with a SHARED resample every replicate's
        # s_p_half value is exactly double that replicate's s_i value -- and since doubling is a monotonic
        # transform, the two CIs must then satisfy the same exact 2x relationship. Resampling the two
        # ratios independently (the bug this guards against) would not reliably preserve it.
        n_i = {"a": [10.0, 0.0, 4.0, 6.0]}
        o_d = {"a": [1.0, 1.0, 1.0, 1.0]}
        n_half = {"a": [20.0, 0.0, 8.0, 12.0]}
        o_c = {"a": [1.0, 1.0, 1.0, 1.0]}
        result = ns.bootstrap_s_i_and_s_phalf(n_i, o_d, n_half, o_c, replicates=500, seed=321)
        assert result["s_p_half"]["ci95"][0] == pytest.approx(2 * result["s_i"]["ci95"][0])
        assert result["s_p_half"]["ci95"][1] == pytest.approx(2 * result["s_i"]["ci95"][1])


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

    def test_a_non_finite_end_reads_undefined_never_partial(self):
        # nan and inf compare False against every threshold, so without an explicit guard these would
        # silently fall through to "inference recovers part".
        assert ns.primary_reading([float("nan"), 0.6]) == "undefined"
        assert ns.primary_reading([0.3, float("nan")]) == "undefined"
        assert ns.primary_reading([float("-inf"), float("inf")]) == "undefined"


class TestDoNoHarm:
    def test_within_band_when_every_resample_is_inside_it(self):
        gains = {"a": [0.01, -0.01, 0.02], "b": [0.0, 0.03]}
        result = ns.do_no_harm(gains, band=0.05)
        assert result["within_band"] is True

    def test_outside_band_when_the_whole_interval_exceeds_it(self):
        gains = {"a": [0.2, 0.2, 0.2], "b": [0.2, 0.2]}  # constant: point and CI are exactly 0.2
        result = ns.do_no_harm(gains, band=0.05)
        assert result["within_band"] is False
        assert result["reading"] == "outside band"
        assert result["ci95"][0] == pytest.approx(0.2)

    def test_empty_data_reads_no_data_never_within_band_or_outside_band(self):
        # an empty dict's bootstrap CI is [nan, nan]; -band <= nan is False, so without the explicit guard
        # this would misread as "within_band: False" (a false failure), not "there is no data here".
        result = ns.do_no_harm({})
        assert result["within_band"] is None
        assert result["reading"] == "no data"

    def test_all_nan_data_also_reads_no_data(self):
        result = ns.do_no_harm({"a": [float("nan"), float("nan")]})
        assert result["within_band"] is None
        assert result["reading"] == "no data"


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


class TestBlameForArm:
    def test_on_naive_consensus_the_bad_source_is_not_ranked_first(self):
        # N's consensus [5,1,0.5,0.5,0.5,0.5]: source 3 (an honest source) has the largest mean absolute
        # deviation (20/6), not source 0 (16/6) or source 1 (11/6) -- naive scoring blames the wrong source.
        reports, mask = _hand_reports(), _hand_mask()
        cons_n = ns.arm_naive(reports, mask)
        result = ns.blame_for_arm(reports, mask, cons_n, bad=0, copier=1)
        assert result["bad_first_credit"] == pytest.approx(0.0)
        assert result["copier_first_credit"] == pytest.approx(0.0)

    def test_on_the_oracle_consensus_the_bad_source_is_ranked_first(self):
        # O's consensus [0,1,0,0.5,0.5,0.5]: source 0's mean absolute deviation (21.5/6) is the largest.
        reports, mask, truth = _hand_reports(), _hand_mask(), _hand_truth()
        cons_o = ns.arm_oracle(reports, mask, truth["bad"], truth["copier"], truth["copied_items"])
        result = ns.blame_for_arm(reports, mask, cons_o, bad=0, copier=1)
        assert result["bad_first_credit"] == pytest.approx(1.0)
        assert result["copier_first_credit"] == pytest.approx(0.0)

    def test_no_copier_gives_no_copier_credit(self):
        reports, mask = _hand_reports(), _hand_mask()
        cons_n = ns.arm_naive(reports, mask)
        result = ns.blame_for_arm(reports, mask, cons_n, bad=0, copier=None)
        assert result["copier_first_credit"] is None


class TestTruthRestsOnDependentReports:
    def test_pins_the_same_item_as_the_ell_based_scale_but_using_the_real_sigma(self):
        # with_collapse (oracle on {0,2}) = [0,1,0,0.5,0.5,0.5]; without_collapse (naive) =
        # [5,1,0.5,0.5,0.5,0.5]; diffs = [5,0,0.5,0,0,0]; 0.5*sigma(1.0) = 0.5, so only item 0 (diff 5)
        # strictly exceeds it -- item 2's diff of exactly 0.5 does not.
        flags = ns.truth_rests_on_dependent_reports(_hand_reports(), _hand_mask(), 0, 1,
                                                     np.array([0, 2]), sigma=1.0)
        np.testing.assert_array_equal(flags, [True, False, False, False, False, False])

    def test_no_copier_or_no_copied_items_gives_all_false(self):
        flags = ns.truth_rests_on_dependent_reports(_hand_reports(), _hand_mask(), 0, None, np.array([]), 1.0)
        assert not flags.any()


class TestFlagCountsAndRecallPrecision:
    def test_counts_true_and_false_positives_and_negatives(self):
        method = np.array([True, True, False, False])
        truth = np.array([True, False, True, False])
        assert ns.flag_counts(method, truth) == {"tp": 1, "fp": 1, "fn": 1}

    def test_recall_and_precision_from_counts(self):
        result = ns.recall_precision_from_counts(tp=3, fp=1, fn=2)
        assert result["recall"] == pytest.approx(3 / 5)
        assert result["precision"] == pytest.approx(3 / 4)

    def test_nan_with_no_positives_at_all(self):
        result = ns.recall_precision_from_counts(tp=0, fp=0, fn=0)
        assert math.isnan(result["recall"]) and math.isnan(result["precision"])


class TestPairwiseMedianSqDiff:
    def test_matches_hand_computed_medians(self):
        medians = ns.pairwise_median_sq_diff(_hand_reports(), _hand_mask())
        expected = {(0, 1): 1.0, (0, 2): 1.0, (0, 3): 9.0, (1, 2): 4.0, (1, 3): 16.0, (2, 3): 4.0}
        for pair, value in expected.items():
            assert medians[pair] == pytest.approx(value)

    def test_the_smallest_pair_on_this_instance_is_the_true_copier_pair(self):
        medians = ns.pairwise_median_sq_diff(_hand_reports(), _hand_mask())
        assert min(medians, key=medians.get) == (0, 1)


# -------------------------------------------------------------------------------------
# The two pinned identities, run against the real generator (a real instance, not hand-made, since the
# identity must hold for whatever the generator draws -- that's the point of "by construction"). The
# generator's own contract (minimums, C/D-identical-reports, chains-only-in-C) is covered by
# tests/test_northstar_graded_fixture.py, not duplicated here.
# -------------------------------------------------------------------------------------

class TestPOnCEqualsOracle:
    def test_p_equals_o_exactly_across_many_real_instances(self):
        cell = {"K": 5, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        for i in range(15):
            inst = graded_fixture.generate(cell, "C", i, seed_root=11)
            mask = ~np.isnan(inst["reports"])
            truth = inst["truth"]
            p = ns.arm_provenance(inst["reports"], mask, inst["chains"])
            o = ns.arm_oracle(inst["reports"], mask, truth["bad"], truth["copier"], truth["copied_items"])
            np.testing.assert_allclose(p, o, equal_nan=True)


class TestCAndDGiveIdenticalN:
    def test_naive_consensus_is_identical_between_c_and_d_across_many_instances(self):
        cell = {"K": 5, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5, "tau": 1.0, "q": 0.25}
        for i in range(15):
            c = graded_fixture.generate(cell, "C", i, seed_root=13)
            d = graded_fixture.generate(cell, "D", i, seed_root=13)
            mask_c = ~np.isnan(c["reports"])
            mask_d = ~np.isnan(d["reports"])
            n_c = ns.arm_naive(c["reports"], mask_c)
            n_d = ns.arm_naive(d["reports"], mask_d)
            np.testing.assert_allclose(n_c, n_d, equal_nan=True)


# -------------------------------------------------------------------------------------
# The fixture spec's pilots and cut
# -------------------------------------------------------------------------------------

class TestChanceAndCut:
    def test_chance_a_is_one_over_k(self):
        assert ns.chance_a(4) == pytest.approx(0.25)

    def test_chance_cd_is_one_over_c_k_2(self):
        assert ns.chance_cd(4) == pytest.approx(1.0 / 6.0)  # C(4,2) = 6

    def test_cut_keeps_between_1_5x_chance_and_point_9(self):
        assert ns.cut_keeps(0.3, chance=0.1) is True    # 1.5*0.1=0.15 <= 0.3 <= 0.9
        assert ns.cut_keeps(0.1, chance=0.1) is False   # 0.1 < 0.15
        assert ns.cut_keeps(0.95, chance=0.1) is False  # 0.95 > 0.9


class TestFullGridEnumeration:
    def test_full_a_cells_is_the_cross_product(self):
        cells = ns.full_a_cells(grid_k=(4, 5), grid_m=(20,), grid_rho=(0.5,), grid_b=(2.0, 4.0),
                                grid_s=(0.5,))
        assert len(cells) == 4  # 2 K x 1 M x 1 rho x 2 b x 1 s
        assert all("tau" not in c for c in cells)

    def test_full_cd_cells_adds_tau_and_q(self):
        cells = ns.full_cd_cells(grid_k=(4,), grid_m=(20,), grid_rho=(0.5,), grid_b=(2.0,), grid_s=(0.5,),
                                 grid_tau=(0.5, 1.0), grid_q=(0.25, 0.5))
        assert len(cells) == 4  # 2 tau x 2 q
        assert all("tau" in c and "q" in c for c in cells)

    def test_the_default_grid_matches_the_fixture_spec(self):
        assert len(ns.full_a_cells()) == 3 * 2 * 2 * 3 * 2       # K x M x rho x b x s
        assert len(ns.full_cd_cells()) == 3 * 2 * 2 * 3 * 2 * 3 * 2  # ... x tau x q


class TestPilotAndCeilingOnRealInstances:
    def test_pilot_a_cell_returns_a_share_between_zero_and_one(self):
        cell = {"K": 4, "M": 20, "rho": 0.5, "b": 8.0, "s": 0.5}
        result = ns.pilot_a_cell(cell, graded_fixture.generate, seed_root=901, n_pilot=20)
        assert 0.0 <= result["share"] <= 1.0
        assert result["chance"] == pytest.approx(0.25)

    def test_pilot_cd_cell_keeps_its_drawn_instances_for_reuse(self):
        cell = {"K": 4, "M": 60, "rho": 0.9, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        result = ns.pilot_cd_cell(cell, graded_fixture.generate, seed_root=902, n_pilot=15)
        assert 0.0 <= result["share"] <= 1.0
        assert len(result["instances"]) == 15

    def test_ceiling_and_auditor_detection_reuse_the_pilot_instances(self):
        cell = {"K": 4, "M": 60, "rho": 0.9, "b": 8.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        result = ns.pilot_cd_cell(cell, graded_fixture.generate, seed_root=903, n_pilot=15)
        ceiling = ns.ceiling_from_pilot_instances(result["instances"])
        assert "pooled_gain_n_minus_o" in ceiling
        detection = ns.auditor_pilot_detection(result["instances"], theta=0.3)
        assert "copier_pair_flagged_rate" in detection


# -------------------------------------------------------------------------------------
# Orchestration: run_cell, and build_plan/run_plan/summarize on a small grid override.
# -------------------------------------------------------------------------------------

class TestRunCell:
    def test_a_cell_rows_carry_every_arm_s_error_blame_and_rests_flags(self):
        cell = {"K": 4, "M": 20, "rho": 0.9, "b": 8.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        rows = ns.run_cell(cell, "D", graded_fixture.generate, seed_root=21, theta=0.1, n_instances=5)
        assert len(rows) == 5
        for row in rows:
            for arm in ("N", "I", "P", "P_half", "O"):
                assert arm in row["consensus_error"]
                assert arm in row["blame"]
            assert "I" in row["rests_on_dependent_reports"] and "P" in row["rests_on_dependent_reports"]
            assert "p_half_missing_share_of_scored" in row

    def test_an_a_cell_has_no_copy_specific_fields(self):
        cell = {"K": 4, "M": 20, "rho": 0.6, "b": 4.0, "s": 0.5}
        rows = ns.run_cell(cell, "A", graded_fixture.generate, seed_root=21, theta=0.1, n_instances=3)
        for row in rows:
            assert "O" not in row["consensus_error"]
            assert row["true_pair"] is None
            assert set(row["blame"]) == {"N", "I"}

    def test_rows_carry_excluded_and_mean_independent_reports(self):
        cell = {"K": 4, "M": 20, "rho": 0.9, "b": 8.0, "s": 0.5, "tau": 0.5, "q": 0.5}
        rows = ns.run_cell(cell, "D", graded_fixture.generate, seed_root=21, theta=0.1, n_instances=5)
        for row in rows:
            assert isinstance(row["excluded"], bool)
            assert "mean_independent_reports_i" in row

    def test_p_half_pairs_is_called_with_chain_named_items_not_truth_copied_items(self, monkeypatch):
        # a stub generator whose chains name a DIFFERENT item set than truth["copied_items"] (chains name
        # only item 0; truth claims items 0 and 2 are copied) -- a spy on p_half_pairs records which array
        # run_cell actually hands it. On the real fixture the two arrays always coincide, so only a
        # deliberately mismatched stub can tell them apart.
        def stub_generator(cell, condition, instance_index, seed_root):
            K, M = 4, 6
            chains = np.full((K, M), None, dtype=object)
            if condition == "C":
                chains[1, 0] = 0
            truth = {"bad": 0, "copier": 1, "biased_items": [0, 2], "copied_items": [0, 2],
                     "true_values": np.zeros(M), "honest_counts_on_copied": {}}
            reports = np.random.default_rng(0).normal(0.0, 1.0, (K, M))  # real variance: avoids the
                                                                         # auditor's own ell_bar==0 edge
            return {"reports": reports, "sigma": 1.0, "chains": chains, "truth": truth, "meta": {}}

        captured = []
        real_p_half_pairs = ns.p_half_pairs

        def spy(chains, copied_items, rng):
            captured.append(sorted(np.asarray(copied_items).tolist()))
            return real_p_half_pairs(chains, copied_items, rng)

        monkeypatch.setattr(ns, "p_half_pairs", spy)
        cell = {"K": 4, "M": 6, "rho": 1.0, "b": 1.0, "s": 1.0, "tau": 0.5, "q": 1.0}
        ns.run_cell(cell, "C", stub_generator, seed_root=1, theta=0.1, n_instances=1)
        assert captured == [[0]]  # chain_named_items(chains) -- never truth's [0, 2]


class TestMissingThetaRaises:
    def test_run_plan_raises_on_a_cd_cell_with_no_calibration(self):
        plan = {
            "cells": [{"cell": {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5, "tau": 0.5, "q": 0.5},
                      "key": "K4_M20_rho0.5_b2.0_s0.5_tau0.5_q0.5", "condition": "C/D"}],
            "calibrations": {},  # deliberately missing K4_M20_rho0.5
            "n_instances": 2, "seeds": {"run": 1},
        }
        with pytest.raises(KeyError):
            ns.run_plan(plan, generator=graded_fixture.generate)


class TestPEqualsOCheck:
    def test_zero_for_identical_rows(self):
        rows = [{"consensus_error": {"P": 0.5, "O": 0.5}}, {"consensus_error": {"P": 1.0, "O": 1.0}}]
        assert ns._p_equals_o_check(rows) == pytest.approx(0.0)

    def test_the_true_maximum_over_every_row(self):
        rows = [{"consensus_error": {"P": 0.5, "O": 0.5}}, {"consensus_error": {"P": 1.3, "O": 1.0}}]
        assert ns._p_equals_o_check(rows) == pytest.approx(0.3)

    def test_both_nan_is_not_a_mismatch(self):
        rows = [{"consensus_error": {"P": float("nan"), "O": float("nan")}}]
        assert ns._p_equals_o_check(rows) == pytest.approx(0.0)

    def test_one_nan_one_finite_reports_as_infinite_never_silently_dropped(self):
        # the old bug used max(running_max, abs(p_err - o_err)); abs(nan - 1.0) is nan, and max(x, nan)
        # silently keeps x, hiding a real P/O mismatch. This must surface, not disappear.
        rows = [{"consensus_error": {"P": float("nan"), "O": 1.0}}]
        assert math.isinf(ns._p_equals_o_check(rows))

    def test_empty_rows_give_zero(self):
        assert ns._p_equals_o_check([]) == pytest.approx(0.0)


def _minimal_a_row(i_all: float, n_all: float) -> dict:
    return {
        "consensus_error": {"I_all": i_all, "N_all": n_all},
        "flagged": [],
        "blame": {"N": {"bad_first_credit": 0.0, "copier_first_credit": None},
                  "I": {"bad_first_credit": 0.0, "copier_first_credit": None}},
    }


class TestSummarizeHighBiasCorner:
    def test_both_s_values_are_pooled_not_one_overwriting_the_other(self):
        # s=0.25's diff is 1.0, s=0.5's diff is 2.0 -- equal-cell-weighted pooled mean is 1.5. The old bug
        # (summarize() overwrote a single gain_i_minus_n_a_high_bias variable with whichever s it saw
        # last) would silently drop one of the two and report 1.0 or 2.0 instead.
        plan = {
            "cells": [
                {"key": "corner_s025", "condition": "A",
                 "cell": {"K": 6, "M": 60, "rho": 0.9, "b": 8.0, "s": 0.25}},
                {"key": "corner_s05", "condition": "A",
                 "cell": {"K": 6, "M": 60, "rho": 0.9, "b": 8.0, "s": 0.5}},
            ],
            "high_bias_corner_a_cells": ["corner_s025", "corner_s05"],
            "do_no_harm_a_cells": [], "primary_population": [], "sensitivity_population": [],
            "primary_population_composition": {}, "do_no_harm_a_composition": {},
        }
        results = {
            "corner_s025": {"A": [_minimal_a_row(1.0, 0.0)]},
            "corner_s05": {"A": [_minimal_a_row(2.0, 0.0)]},
        }
        summary = ns.summarize(plan, results)
        assert summary["do_no_harm"]["high_bias_corner"]["point"] == pytest.approx(1.5)

    def test_does_not_conflate_with_do_no_harm_a_cells(self):
        # a cell in do_no_harm_a_cells but not the corner must not leak into the corner's own pool.
        plan = {
            "cells": [
                {"key": "base_cell", "condition": "A",
                 "cell": {"K": 4, "M": 20, "rho": 0.5, "b": 2.0, "s": 0.5}},
                {"key": "corner_s025", "condition": "A",
                 "cell": {"K": 6, "M": 60, "rho": 0.9, "b": 8.0, "s": 0.25}},
            ],
            "high_bias_corner_a_cells": ["corner_s025"],
            "do_no_harm_a_cells": ["base_cell"], "primary_population": [], "sensitivity_population": [],
            "primary_population_composition": {}, "do_no_harm_a_composition": {},
        }
        results = {
            "base_cell": {"A": [_minimal_a_row(100.0, 0.0)]},
            "corner_s025": {"A": [_minimal_a_row(1.0, 0.0)]},
        }
        summary = ns.summarize(plan, results)
        assert summary["do_no_harm"]["high_bias_corner"]["point"] == pytest.approx(1.0)
        assert summary["do_no_harm"]["pooled"]["point"] == pytest.approx(100.0)


class TestPrimaryPopulationGate:
    def test_every_primary_member_clears_the_gate_and_every_non_member_does_not(self):
        # a wider grid (every tau, both q, at a modest b and s) to get a real mix of pilot N-O gains --
        # some cells should clear CEILING_GATE_SIGMA and some should not. The gate's whole job is to keep
        # them apart.
        plan = ns.build_plan(
            generator=graded_fixture.generate, seed_root_calibration=1, seed_root_pilot=2, seed_root_run=3,
            n_cal=20, n_pilot=40, n_instances=5, grid_k=(6,), grid_m=(20,), grid_rho=(0.9,),
            grid_b=(2.0,), grid_s=(0.25,), grid_tau=(0.5, 1.5), grid_q=(0.25, 0.5))
        gains = plan["pilot"]["cd"]
        assert any(g["pilot_gain_n_minus_o"] >= ns.CEILING_GATE_SIGMA for g in gains.values())
        assert any(g["pilot_gain_n_minus_o"] < ns.CEILING_GATE_SIGMA for g in gains.values()), (
            "this grid is expected to produce a mix; widen it if every cell cleared the gate")
        primary = set(plan["primary_population"])
        for key, pilot_entry in gains.items():
            clears = pilot_entry["pilot_gain_n_minus_o"] >= ns.CEILING_GATE_SIGMA
            assert (key in primary) == clears, (
                f"{key}: gain {pilot_entry['pilot_gain_n_minus_o']} clears={clears} "
                f"but membership={key in primary}")


class TestBuildPlanAndRunPlan:
    GRID_KWARGS = dict(grid_k=(4,), grid_m=(20,), grid_rho=(0.9,), grid_b=(8.0,), grid_s=(0.5,),
                       grid_tau=(0.5,), grid_q=(0.5,))

    def test_build_plan_runs_the_pilot_cut_and_calibration_on_a_small_grid(self):
        plan = ns.build_plan(
            generator=graded_fixture.generate, seed_root_calibration=1, seed_root_pilot=2,
            seed_root_run=3, n_cal=30, n_pilot=15, n_instances=10, **self.GRID_KWARGS)
        assert plan["calibrations"]
        assert len(plan["cells"]) + len(plan["dropped_cells"]) == 2  # 1 A cell + 1 C/D cell
        for entry in plan["calibrations"].values():
            assert np.isfinite(entry["theta"])

    def test_run_plan_and_summarize_end_to_end(self):
        plan = ns.build_plan(
            generator=graded_fixture.generate, seed_root_calibration=1, seed_root_pilot=2,
            seed_root_run=3, n_cal=30, n_pilot=15, n_instances=8, **self.GRID_KWARGS)
        results = ns.run_plan(plan, generator=graded_fixture.generate)
        summary = ns.summarize(plan, results)
        assert summary["primary"]["s_i"]["reading"] in (
            "inference substitutes for the record", "the record can't be replaced by this inference",
            "inference recovers part", "undefined")
        assert "pooled_gain_n_minus_o" in summary["primary"]["ceiling"]
        assert "population_composition" in summary["primary"]
        assert summary["checks"]["n_identical_between_c_and_d"] is True
        assert summary["checks"]["p_on_c_equals_o_max_abs_diff"] == pytest.approx(0.0, abs=1e-9)
        assert "auditor_helps" in summary["inference_at_all"]
        assert "D" in summary["detection"] and "A_false_flag_rate" in summary["detection"]
        assert "s_p_half" in summary["per_cell"] and "p_half_missing_share_of_scored" in summary["per_cell"]
        assert "I_on_D" in summary["rests_on_dependent_reports"]
        assert "P_on_C" in summary["rests_on_dependent_reports"]
        assert summary["sensitivity"]["n_cells"] >= 0
        for arm in ("N", "I", "O"):
            assert arm in summary["blame"]["D"]
        for arm in ("P", "P_half"):
            assert arm in summary["blame"]["C"]
        assert "a_composition" in summary["do_no_harm"]
        assert "excluded_instances" in summary["primary"]


# -------------------------------------------------------------------------------------
# A tiny end-to-end CLI smoke on the real generator: tiny n_cal/n_pilot/n_instances over the fixture
# spec's full grid shape, just to show the plan -> run -> rescore pipe works. Not a real run -- the real
# plan needs the full 500 calibration/pilot/run counts, not these tiny stand-ins.
# -------------------------------------------------------------------------------------

class TestCliSmokeEndToEnd:
    def test_plan_run_rescore_round_trip(self, tmp_path):
        plan_path = tmp_path / "plan.json"
        results_path = tmp_path / "results.json"
        engram_root = str(Path(ns.__file__).resolve().parents[2])
        module_args = [sys.executable, "-m", "experiments.northstar.test7"]

        plan_proc = subprocess.run(
            module_args + ["plan", "--out", str(plan_path),
                          "--n-cal", "10", "--n-pilot", "5", "--n-instances", "5"],
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
        assert "primary" in summary and "reading" in summary["primary"]["s_i"]
