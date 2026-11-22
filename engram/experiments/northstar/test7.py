"""North-star test 7: kept provenance against inferred independence.

Spec: ``docs/superpowers/specs/2026-11-22-north-star-test-7-design.md`` (approved, revision 3), built on
Tardis's graded-blame fixture, ``docs/superpowers/specs/2026-11-22-graded-blame-fixture-design.md`` (approved,
revision 3). That spec fixes the fixture (K sources, M items, overlap rho, one bad source, one copier in C
and D); this module is everything downstream of one instance's ``reports``/``chains``/``truth``: the auditor
that infers which pairs of sources are dependent, the five arms that each turn an instance into one
consensus per item, the scoring that compares them, and the bootstrap, readings and do-no-harm/ceiling
checks that turn many instances into the primary.

Numpy only. The fixture generator is Tardis's ``experiments.northstar.graded_fixture.generate`` (merged
867614fa, approved); earlier rounds of this module built against a stub with the same interface
(``generate(cell, condition, instance_index, seed_root) -> Instance``) while her module didn't exist yet,
and that stub has since been dropped in favour of the real thing.

A "cell" is a dict with at least K, M, rho, b, s; a C or D cell also carries tau, q. Every axis must be a
plain Python ``int``/``float`` (never a numpy scalar): the fixture's own seed key hashes each axis's
``repr()``, so a ``numpy.float64`` and a ``float`` with the same value would seed differently. ``condition``
is one of "A", "C", "D".
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.northstar.graded_fixture import generate as GENERATOR

# ======================================================================================
# Constants
# ======================================================================================

PAIR_MIN_SHARED = 4          # ell(i,j) needs at least this many items both i and j report
CHI2_1_LOWER_QUARTILE_OVER_2 = 0.1015   # the chi-squared_1 25th percentile, divided by 2 (R4's s-hat formula)
CALIBRATION_PERCENTILE = 5    # theta is the 5th percentile of each A calibration instance's min r
CEILING_FLOOR_SIGMA = 0.1      # the ceiling stop: pooled N-O under this many sigma means the test stops
DO_NO_HARM_BAND_SIGMA = 0.05    # the do-no-harm interval must lie within +/- this many sigma

BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 2026112207

GRID_B = (2.0, 4.0, 8.0)
GRID_S = (0.25, 0.5)
GRID_RHO = (0.5, 0.9)
GRID_K = (4, 5, 6)
GRID_M = (20, 60)
GRID_TAU = (0.5, 1.0, 1.5)
GRID_Q = (0.25, 0.5)

PRIMARY_LOWER_SUBSTITUTES = 0.8
PRIMARY_UPPER_CANT_REPLACE = 0.5

PILOT_INSTANCES = 100          # the fixture spec's own pilot size, per cell
PILOT_MIN_SHARED = 3           # the pilot's plain copier detector: a pair needs at least this many shared items
PILOT_CUT_LOWER = 1.5          # kept where the pilot share is between 1.5x chance...
PILOT_CUT_UPPER = 0.9          # ...and 0.9


# ======================================================================================
# The auditor: inferred independence
# ======================================================================================

def pairwise_lower_quartile(reports: np.ndarray, mask: np.ndarray, min_shared: int = PAIR_MIN_SHARED) -> dict:
    """ell(i, j): the 25th percentile of (x_i - x_j)^2 over the items both i and j report, for every pair
    sharing at least ``min_shared`` items. Scale-free, needs no sigma, uses no truth."""
    K = reports.shape[0]
    ell = {}
    for i, j in itertools.combinations(range(K), 2):
        both = mask[i] & mask[j]
        if int(both.sum()) >= min_shared:
            ell[(i, j)] = float(np.percentile((reports[i, both] - reports[j, both]) ** 2, 25))
    return ell


def ell_bar(ell: dict) -> float | None:
    """The reference: the median of ell over the instance's eligible pairs. None with fewer than one pair."""
    return float(np.median(list(ell.values()))) if ell else None


def pair_ratios(ell: dict) -> dict:
    """r(i, j) = ell(i, j) / ell_bar, the median of ell over the instance's eligible pairs."""
    if not ell:
        return {}
    ref = ell_bar(ell)
    return {pair: value / ref for pair, value in ell.items()}


def flagged_pairs(ratios: dict, theta: float) -> list[tuple[int, int]]:
    """Every pair with r below theta is marked dependent."""
    return [pair for pair, r in ratios.items() if r < theta]


def scale_estimate(ell: dict) -> float | None:
    """s-hat = sqrt(ell_bar / (2 * 0.1015)): for two independent reports with noise sigma, the 25th
    percentile of (x_i - x_j)^2 is 2*sigma^2 * 0.1015, the chi-squared_1 lower quartile (R4)."""
    ref = ell_bar(ell)
    if ref is None:
        return None
    return float(np.sqrt(ref / (2 * CHI2_1_LOWER_QUARTILE_OVER_2)))


def auditor_pairs(reports: np.ndarray, mask: np.ndarray, theta: float,
                   min_shared: int = PAIR_MIN_SHARED) -> tuple[list[tuple[int, int]], dict, float | None]:
    """One call that runs the whole auditor on an instance: ell, the flagged pairs at ``theta``, and the
    scale estimate (all three share the same ell_bar)."""
    ell = pairwise_lower_quartile(reports, mask, min_shared)
    ratios = pair_ratios(ell)
    return flagged_pairs(ratios, theta), ell, scale_estimate(ell)


def calibrate_theta(K: int, M: int, rho: float, generator, seed_root: int, *, n_cal: int = 500,
                     b_grid: tuple = GRID_B, s_grid: tuple = GRID_S,
                     percentile: float = CALIBRATION_PERCENTILE) -> dict:
    """theta, fixed on A instances per (K, M, rho): the 5th percentile of each instance's min r, over
    ``n_cal`` calibration instances pooled over b and s (which the auditor can't count, R3). Also returns
    the false-flag rate per (b, s), for the plan to record."""
    rng = np.random.default_rng(np.random.SeedSequence([int(seed_root), int(K), int(M), int(round(rho * 1000))]))
    mins_by_bs: dict = {}
    all_mins = []
    for i in range(n_cal):
        b = float(rng.choice(b_grid))
        s = float(rng.choice(s_grid))
        inst = generator({"K": K, "M": M, "rho": rho, "b": b, "s": s}, "A", i, seed_root)
        mask = ~np.isnan(inst["reports"])
        ell = pairwise_lower_quartile(inst["reports"], mask)
        ratios = pair_ratios(ell)
        if not ratios:
            continue
        r_min = min(ratios.values())
        all_mins.append(r_min)
        mins_by_bs.setdefault((b, s), []).append(r_min)
    theta = float(np.percentile(all_mins, percentile)) if all_mins else float("nan")
    false_flag_rate = {f"b{b}_s{s}": float(np.mean(np.asarray(vals) < theta))
                        for (b, s), vals in mins_by_bs.items()}
    return {"theta": theta, "n_cal": n_cal, "n_valid": len(all_mins), "false_flag_rate": false_flag_rate}


# ======================================================================================
# The consensus and collapse
# ======================================================================================

def collapse_consensus(reports: np.ndarray, mask: np.ndarray, pair_specs: list) -> np.ndarray:
    """Every item's consensus is the median of the reports it counts. ``pair_specs`` is a list of
    (i, j, items): on item m, if both i and j report m and (items is None or m in items), their two reports
    become one, their mean; every other report on that item is kept as-is. A source appears in at most one
    collapsed pair per item (first match wins; the arms below never build overlapping specs)."""
    K, M = reports.shape
    consensus = np.full(M, np.nan)
    for m in range(M):
        reporters = np.where(mask[:, m])[0]
        if len(reporters) == 0:
            continue
        values = {k: reports[k, m] for k in reporters}
        used: set = set()
        merged = []
        for (i, j, items) in pair_specs:
            if i in used or j in used or i not in values or j not in values:
                continue
            if items is not None and m not in items:
                continue
            merged.append((values[i] + values[j]) / 2.0)
            used.add(i)
            used.add(j)
        for k in reporters:
            if k not in used:
                merged.append(values[k])
        consensus[m] = float(np.median(merged))
    return consensus


def rests_on_dependent_reports(reports: np.ndarray, mask: np.ndarray, pair_specs: list,
                                s_hat: float | None) -> np.ndarray:
    """Per item: whether undoing the collapse (recomputing its consensus with none of ``pair_specs``
    merged) moves the consensus by more than 0.5*s_hat. False everywhere if there is nothing to undo or no
    scale estimate."""
    M = reports.shape[1]
    if not pair_specs or s_hat is None or not np.isfinite(s_hat) or s_hat == 0:
        return np.zeros(M, dtype=bool)
    with_collapse = collapse_consensus(reports, mask, pair_specs)
    without_collapse = collapse_consensus(reports, mask, [])
    return np.abs(with_collapse - without_collapse) > 0.5 * s_hat


# ======================================================================================
# The five arms
# ======================================================================================

def arm_naive(reports: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """N: every report, nothing collapsed."""
    return collapse_consensus(reports, mask, [])


def provenance_pairs(chains: np.ndarray) -> list[tuple[int, int, set]]:
    """The pairs a declared chain names, grouped by pair with every item each one names collected together
    (``chains[k, m]`` is the named source index for report (k, m), or None)."""
    K, M = chains.shape
    groups: dict[tuple[int, int], set] = {}
    for k in range(K):
        for m in range(M):
            named = chains[k, m]
            if named is not None:
                pair = (int(named), k) if named < k else (k, int(named))
                groups.setdefault(pair, set()).add(m)
    return [(i, j, items) for (i, j), items in groups.items()]


def arm_provenance(reports: np.ndarray, mask: np.ndarray, chains: np.ndarray) -> np.ndarray:
    """P, kept provenance: every report, with the pairs ``relation()`` (here, ``chains``) answers copied
    collapsed on their copied items."""
    return collapse_consensus(reports, mask, provenance_pairs(chains))


def p_half_drop_seed(cell: dict, instance_index: int, seed_root: int) -> np.random.Generator:
    """The instance seed for P-half's draw of which copied items lose their chain: deterministic per
    instance, disjoint from the fixture's own draws (tag 97 is arbitrary but fixed)."""
    entropy = [int(seed_root), 97, int(round(cell["K"])), int(round(cell["M"])),
               int(round(cell["rho"] * 1000)), int(round(cell["b"] * 1000)), int(round(cell["s"] * 1000)),
               int(round(cell.get("tau", 0.0) * 1000)), int(round(cell.get("q", 0.0) * 1000)),
               int(instance_index)]
    return np.random.default_rng(np.random.SeedSequence(entropy))


def p_half_pairs(chains: np.ndarray, copied_items: np.ndarray, rng: np.random.Generator) -> list:
    """As ``provenance_pairs``, but ceil(n/2) of the instance's n copied items, drawn from all of them with
    ``rng``, carry no chain, so only the rest collapse."""
    all_pairs = provenance_pairs(chains)
    n = len(copied_items)
    if n == 0:
        return all_pairs
    n_drop = math.ceil(n / 2)
    dropped = set(rng.choice(copied_items, size=min(n_drop, n), replace=False).tolist())
    out = []
    for (i, j, items) in all_pairs:
        kept = items - dropped
        if kept:
            out.append((i, j, kept))
    return out


def arm_inferred(reports: np.ndarray, mask: np.ndarray, theta: float,
                  min_shared: int = PAIR_MIN_SHARED) -> tuple[np.ndarray, list, dict, float | None]:
    """I, inferred: every report, with the auditor's flagged pairs collapsed (on every item the pair
    shares, not only the items that happen to be copied -- the auditor doesn't know which those are)."""
    flagged, ell, s_hat = auditor_pairs(reports, mask, theta, min_shared)
    pair_specs = [(i, j, None) for (i, j) in flagged]
    return collapse_consensus(reports, mask, pair_specs), flagged, ell, s_hat


def arm_oracle(reports: np.ndarray, mask: np.ndarray, bad: int, copier: int | None,
                copied_items) -> np.ndarray:
    """O, the oracle: every report, with the truth's copier pair collapsed on its copied items.
    ``copied_items`` may be a list or an array (the real fixture's truth gives a plain list)."""
    pair_specs = [(min(bad, copier), max(bad, copier), set(np.asarray(copied_items, dtype=int).tolist()))] \
        if copier is not None and len(copied_items) else []
    return collapse_consensus(reports, mask, pair_specs)


# ======================================================================================
# Scoring
# ======================================================================================

def scored_items(truth: dict) -> np.ndarray:
    """The scored items: in C and D, the copied *biased* items, those where the bad source's report
    carries the bias and the copier copied it, per the truth. The truth only selects and scores."""
    copied = np.asarray(truth["copied_items"], dtype=int)
    biased = np.asarray(truth["biased_items"], dtype=int)
    return np.intersect1d(copied, biased)


def consensus_error(consensus: np.ndarray, true_values: np.ndarray, sigma: float, items: np.ndarray) -> float:
    """|consensus - true value| / sigma, averaged over ``items`` for one instance. NaN with no items (an
    instance with no scored item is excluded by the caller and counted, per spec, not silently zeroed)."""
    if len(items) == 0:
        return float("nan")
    return float(np.mean(np.abs(consensus[items] - true_values[items]) / sigma))


def pooled_gain(per_cell_values: dict) -> float:
    """The equally-weighted mean of each cell's own mean value: cells count equally, never their instance
    counts. NaN entries and empty cells are dropped before a cell's own mean is taken. Reused by the
    primary, do-no-harm, the ceiling count, and the per-cell descriptive ratios."""
    means = []
    for values in per_cell_values.values():
        arr = np.asarray(values, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr):
            means.append(float(arr.mean()))
    return float(np.mean(means)) if means else float("nan")


def s_i_ratio(gain_n_minus_i_by_cell: dict, gain_n_minus_o_by_cell: dict) -> float:
    """The primary, on D: S_I = pooled(N-I) / pooled(N-O), each cell's gain weighted equally. The share of a
    kept record's value the auditor gets back without one."""
    numerator = pooled_gain(gain_n_minus_i_by_cell)
    denominator = pooled_gain(gain_n_minus_o_by_cell)
    return numerator / denominator


def per_cell_ratios(numerator_by_cell: dict, denominator_by_cell: dict, *,
                     floor: float = CEILING_FLOOR_SIGMA) -> dict:
    """S_I and S_P-half per cell, descriptive only, where that cell's own mean denominator is at least
    ``floor`` sigma (otherwise the ratio is too noisy to read, so it is left out)."""
    out = {}
    for key in sorted(set(numerator_by_cell) & set(denominator_by_cell)):
        den = np.asarray(denominator_by_cell[key], dtype=float)
        den = den[~np.isnan(den)]
        if len(den) == 0 or den.mean() < floor:
            continue
        num = np.asarray(numerator_by_cell[key], dtype=float)
        num = num[~np.isnan(num)]
        out[key] = float(num.mean() / den.mean()) if len(num) else float("nan")
    return out


# ======================================================================================
# The bootstrap
# ======================================================================================

def bootstrap_ratio_ci(numerator_by_cell: dict, denominator_by_cell: dict, *,
                        replicates: int = BOOTSTRAP_REPLICATES, seed: int = BOOTSTRAP_SEED) -> dict:
    """The primary's bootstrap: resamples each cell's base instances independently, with replacement,
    keeping a resampled instance's numerator and denominator values paired (both came from it), then takes
    the equally-weighted pooled ratio of each resample. 10,000 replicates, seed 2026112207, percentile 95%
    intervals."""
    rng = np.random.default_rng(seed)
    keys = sorted(set(numerator_by_cell) & set(denominator_by_cell))
    arrays = {}
    for key in keys:
        num = np.asarray(numerator_by_cell[key], dtype=float)
        den = np.asarray(denominator_by_cell[key], dtype=float)
        valid = ~(np.isnan(num) | np.isnan(den))
        arrays[key] = (num[valid], den[valid])
    boot = np.empty(replicates)
    for r in range(replicates):
        num_means, den_means = [], []
        for key in keys:
            num, den = arrays[key]
            n = len(num)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)
            num_means.append(num[idx].mean())
            den_means.append(den[idx].mean())
        boot[r] = (float(np.mean(num_means)) / float(np.mean(den_means))) if den_means else float("nan")
    point = s_i_ratio(numerator_by_cell, denominator_by_cell)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    return {"point": float(point), "ci95": [float(lo), float(hi)]}


def bootstrap_pooled_mean_ci(values_by_cell: dict, *, replicates: int = BOOTSTRAP_REPLICATES,
                              seed: int = BOOTSTRAP_SEED) -> dict:
    """A pooled, equally-weighted mean's bootstrap CI (do-no-harm's I-N direction, and the auditor-helps
    check), resampling each cell's base instances independently with replacement."""
    rng = np.random.default_rng(seed)
    arrays = {}
    for key, values in values_by_cell.items():
        arr = np.asarray(values, dtype=float)
        arrays[key] = arr[~np.isnan(arr)]
    keys = list(arrays)
    boot = np.empty(replicates)
    for r in range(replicates):
        means = []
        for key in keys:
            arr = arrays[key]
            n = len(arr)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)
            means.append(arr[idx].mean())
        boot[r] = float(np.mean(means)) if means else float("nan")
    point = pooled_gain(values_by_cell)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    return {"point": float(point), "ci95": [float(lo), float(hi)]}


# ======================================================================================
# Readings, do-no-harm and the ceiling
# ======================================================================================

def primary_reading(ci95: list) -> str:
    """The readings, fixed by the spec: "inference substitutes for the record" if the lower end is 0.8 or
    more; "the record can't be replaced by this inference" if the upper end is under 0.5; else "inference
    recovers part"."""
    lower, upper = ci95
    if lower >= PRIMARY_LOWER_SUBSTITUTES:
        return "inference substitutes for the record"
    if upper < PRIMARY_UPPER_CANT_REPLACE:
        return "the record can't be replaced by this inference"
    return "inference recovers part"


def do_no_harm(gain_i_minus_n_by_cell: dict, *, band: float = DO_NO_HARM_BAND_SIGMA) -> dict:
    """Do no harm, A: I against N, consensus error over all items the bad source reports. The interval for
    I-N must lie within +/- ``band`` sigma; outside it, false collapses cost honest conclusions, reported as
    a failure."""
    result = bootstrap_pooled_mean_ci(gain_i_minus_n_by_cell)
    lo, hi = result["ci95"]
    result["within_band"] = bool(-band <= lo and hi <= band)
    return result


def ceiling_check(gain_n_minus_o_by_cell: dict, *, floor: float = CEILING_FLOOR_SIGMA) -> dict:
    """The ceiling, counted before the plan is fixed: the oracle's gain N-O on copied biased items, pooled
    equally across kept cells. Under ``floor`` sigma, double counting barely moves these conclusions and the
    test stops with that as its result."""
    pooled = pooled_gain(gain_n_minus_o_by_cell)
    return {"pooled_gain_n_minus_o": pooled, "stop": bool(not np.isnan(pooled) and pooled < floor)}


def gap_delta(err_i_on_d_by_cell: dict, err_p_on_c_by_cell: dict) -> dict:
    """Beside the primary, every time it's read: Delta = I_D - P_C in sigma, with its interval. Mostly the
    ceiling the cut already guaranteed, so never read alone as evidence the auditor was tested hard."""
    diff_by_cell = {}
    for key in sorted(set(err_i_on_d_by_cell) & set(err_p_on_c_by_cell)):
        i_vals = np.asarray(err_i_on_d_by_cell[key], dtype=float)
        p_vals = np.asarray(err_p_on_c_by_cell[key], dtype=float)
        n = min(len(i_vals), len(p_vals))
        diff_by_cell[key] = (i_vals[:n] - p_vals[:n]).tolist()
    return bootstrap_pooled_mean_ci(diff_by_cell)


# ======================================================================================
# Secondary: detection and blame
# ======================================================================================

def detection_rates(rows: list) -> dict:
    """D: the share of instances with the copier pair flagged, the share with an honest pair flagged, and
    the mean number of honest pairs flagged per such instance (A4). Each row needs "flagged" (a list of
    pairs) and "true_pair" (the sorted (bad, copier) tuple, or None in A)."""
    copier_flagged = []
    honest_flagged = []
    honest_counts = []
    for row in rows:
        true_pair = row.get("true_pair")
        flagged = [tuple(p) for p in row["flagged"]]
        if true_pair is None:
            continue
        true_pair = tuple(true_pair)
        copier_flagged.append(true_pair in flagged)
        honest = [p for p in flagged if p != true_pair]
        honest_flagged.append(len(honest) > 0)
        if honest:
            honest_counts.append(len(honest))
    return {
        "copier_pair_flagged_rate": float(np.mean(copier_flagged)) if copier_flagged else float("nan"),
        "honest_pair_flagged_rate": float(np.mean(honest_flagged)) if honest_flagged else float("nan"),
        "mean_honest_pairs_flagged_when_any": float(np.mean(honest_counts)) if honest_counts else float("nan"),
    }


def false_flag_rate_a(rows: list) -> float:
    """A: the realised false-flag rate per cell -- the share of A instances with any flagged pair at all."""
    any_flagged = [len(row["flagged"]) > 0 for row in rows]
    return float(np.mean(any_flagged)) if any_flagged else float("nan")


def blame_scores(reports: np.ndarray, mask: np.ndarray, consensus: np.ndarray) -> np.ndarray:
    """Each source's mean absolute deviation from ``consensus``, over the items it reports (a score per
    source, never a sum, the fixture spec's scoring rule)."""
    K = reports.shape[0]
    scores = np.full(K, np.nan)
    for k in range(K):
        items = mask[k]
        if items.sum() == 0:
            continue
        scores[k] = float(np.mean(np.abs(reports[k, items] - consensus[items])))
    return scores


def blame_first_credit(scores: np.ndarray, target: int, rel_tol: float = 1e-9) -> float:
    """Fractional credit (1/t) that ``target`` ranks first for blame (the largest mean absolute deviation),
    a tie being within ``rel_tol`` times the largest score (the fixture spec's N1 tolerance convention)."""
    valid = np.where(~np.isnan(scores))[0]
    if target not in valid:
        return 0.0
    max_score = float(np.max(scores[valid]))
    tol = rel_tol * max_score
    tied_for_first = [k for k in valid if (max_score - scores[k]) <= tol]
    if target not in tied_for_first:
        return 0.0
    return 1.0 / len(tied_for_first)


def blame_for_arm(reports: np.ndarray, mask: np.ndarray, consensus: np.ndarray, bad: int,
                   copier: int | None) -> dict:
    """Blame for one arm's consensus: the bad source's and the copier's first-place credit (a copier
    ranking first is scored apart from the bad source ranking first, the fixture spec's rule)."""
    scores = blame_scores(reports, mask, consensus)
    return {
        "bad_first_credit": blame_first_credit(scores, bad),
        "copier_first_credit": blame_first_credit(scores, copier) if copier is not None else None,
    }


def truth_rests_on_dependent_reports(reports: np.ndarray, mask: np.ndarray, bad: int, copier: int | None,
                                      copied_items: np.ndarray, sigma: float) -> np.ndarray:
    """The ground truth for "rests on dependent reports": where the oracle's collapse (the truth's copier
    pair, on its copied items) moves the consensus by more than 0.5*sigma -- the real sigma, never an
    estimate (unlike the auditor's own ŝ-based flag, which this is compared against)."""
    if copier is None or len(copied_items) == 0:
        return np.zeros(reports.shape[1], dtype=bool)
    pair_specs = [(min(bad, copier), max(bad, copier), set(np.asarray(copied_items, dtype=int).tolist()))]
    with_collapse = collapse_consensus(reports, mask, pair_specs)
    without_collapse = collapse_consensus(reports, mask, [])
    return np.abs(with_collapse - without_collapse) > 0.5 * sigma


def flag_counts(method_flags: np.ndarray, truth_flags: np.ndarray) -> dict:
    """True/false positive/negative counts of ``method_flags`` against ``truth_flags``, meant to be summed
    across instances before recall/precision is taken (pooling raw counts, not averaging per-instance
    rates, which would be undefined whenever an instance has no truth-positive item)."""
    return {
        "tp": int(np.sum(method_flags & truth_flags)),
        "fp": int(np.sum(method_flags & ~truth_flags)),
        "fn": int(np.sum(~method_flags & truth_flags)),
    }


def recall_precision_from_counts(tp: int, fp: int, fn: int) -> dict:
    return {
        "recall": (tp / (tp + fn)) if (tp + fn) > 0 else float("nan"),
        "precision": (tp / (tp + fp)) if (tp + fp) > 0 else float("nan"),
    }


# ======================================================================================
# The fixture spec's pilots and cut (93e08797, "The grid, after a pilot")
# ======================================================================================

def pairwise_median_sq_diff(reports: np.ndarray, mask: np.ndarray,
                             min_shared: int = PILOT_MIN_SHARED) -> dict:
    """The pilot's plain copier detector: the median squared difference per pair sharing at least
    ``min_shared`` items -- no structure, no sigma, not the auditor's lower-quartile statistic (N4)."""
    K = reports.shape[0]
    out = {}
    for i, j in itertools.combinations(range(K), 2):
        both = mask[i] & mask[j]
        if int(both.sum()) >= min_shared:
            out[(i, j)] = float(np.median((reports[i, both] - reports[j, both]) ** 2))
    return out


def chance_a(K: int) -> float:
    """Chance, A: 1/K for the bad source ranking first by blame."""
    return 1.0 / K


def chance_cd(K: int) -> float:
    """Chance, C/D: 1/C(K,2) for the copier pair being the one the plain detector finds."""
    return 1.0 / math.comb(K, 2)


def cut_keeps(share: float, chance: float, *, lower: float = PILOT_CUT_LOWER,
               upper: float = PILOT_CUT_UPPER) -> bool:
    """The fixture spec's cut: a cell is kept where its pilot's share is between 1.5x chance and 0.9."""
    return (lower * chance) <= share <= upper


def full_a_cells(*, grid_k=GRID_K, grid_m=GRID_M, grid_rho=GRID_RHO, grid_b=GRID_B, grid_s=GRID_S) -> list:
    """Every A cell in the fixture spec's grid (K x M x rho x b x s); overridable for a fast test grid."""
    return [{"K": K, "M": M, "rho": rho, "b": b, "s": s}
            for K in grid_k for M in grid_m for rho in grid_rho for b in grid_b for s in grid_s]


def full_cd_cells(*, grid_k=GRID_K, grid_m=GRID_M, grid_rho=GRID_RHO, grid_b=GRID_B, grid_s=GRID_S,
                   grid_tau=GRID_TAU, grid_q=GRID_Q) -> list:
    """Every C/D cell in the fixture spec's grid (the A axes plus tau x q); overridable for a fast test
    grid. One cell serves both C and D -- their reports are identical, differing only in chains."""
    return [{"K": K, "M": M, "rho": rho, "b": b, "s": s, "tau": tau, "q": q}
            for K in grid_k for M in grid_m for rho in grid_rho for b in grid_b for s in grid_s
            for tau in grid_tau for q in grid_q]


def pilot_a_cell(cell: dict, generator, seed_root: int, n_pilot: int = PILOT_INSTANCES) -> dict:
    """The pilot for an A cell: the plain median's naive consensus, scored by mean absolute deviation
    (blame); the share the bad source ranks first (fractional credit on ties, N1's tolerance)."""
    credits = []
    for i in range(n_pilot):
        inst = generator(cell, "A", i, seed_root)
        mask = ~np.isnan(inst["reports"])
        consensus = arm_naive(inst["reports"], mask)
        scores = blame_scores(inst["reports"], mask, consensus)
        credits.append(blame_first_credit(scores, inst["truth"]["bad"]))
    return {"share": float(np.mean(credits)) if credits else float("nan"), "chance": chance_a(cell["K"]),
            "n_pilot": n_pilot}


def pilot_cd_cell(cell: dict, generator, seed_root: int, n_pilot: int = PILOT_INSTANCES) -> dict:
    """The pilot for a C/D cell: the plain copier detector on condition C's reports (identical to D's); the
    share it finds the true copier pair. Keeps the drawn instances so the ceiling count and the auditor's
    pilot detection rate can reuse them without redrawing."""
    hits = []
    instances = []
    for i in range(n_pilot):
        inst = generator(cell, "C", i, seed_root)
        instances.append(inst)
        mask = ~np.isnan(inst["reports"])
        pairwise = pairwise_median_sq_diff(inst["reports"], mask)
        truth = inst["truth"]
        true_pair = tuple(sorted((truth["bad"], truth["copier"])))
        detected = min(pairwise, key=pairwise.get) if pairwise else None
        hits.append(detected == true_pair)
    return {"share": float(np.mean(hits)) if hits else float("nan"), "chance": chance_cd(cell["K"]),
            "n_pilot": n_pilot, "instances": instances}


def ceiling_from_pilot_instances(instances: list) -> dict:
    """The ceiling count on already-drawn pilot instances: the oracle's gain N-O on copied biased items,
    and the share of those items the naive consensus misses by more than 0.5 sigma."""
    gains, off_shares = [], []
    for inst in instances:
        truth = inst["truth"]
        mask = ~np.isnan(inst["reports"])
        scored = scored_items(truth)
        if len(scored) == 0:
            continue
        true_values = np.asarray(truth["true_values"], dtype=float)
        cons_n = arm_naive(inst["reports"], mask)
        copied_items = np.asarray(truth["copied_items"], dtype=int)
        cons_o = arm_oracle(inst["reports"], mask, truth["bad"], truth["copier"], copied_items)
        err_n = consensus_error(cons_n, true_values, inst["sigma"], scored)
        err_o = consensus_error(cons_o, true_values, inst["sigma"], scored)
        gains.append(err_n - err_o)
        off_shares.append(float(np.mean(np.abs(cons_n[scored] - true_values[scored]) / inst["sigma"] > 0.5)))
    return {"pooled_gain_n_minus_o": float(np.mean(gains)) if gains else float("nan"),
            "share_off_by_half_sigma": float(np.mean(off_shares)) if off_shares else float("nan"),
            "n_valid": len(gains)}


def auditor_pilot_detection(instances: list, theta: float) -> dict:
    """The auditor's pilot detection rate per kept cell: on the same pilot instances, using the calibrated
    theta, for the plan's own record (distinct from the plain detector's own cut decision above)."""
    rows = []
    for inst in instances:
        mask = ~np.isnan(inst["reports"])
        flagged, _, _ = auditor_pairs(inst["reports"], mask, theta)
        truth = inst["truth"]
        rows.append({"flagged": [list(p) for p in flagged], "true_pair": sorted((truth["bad"], truth["copier"]))})
    return detection_rates(rows)


def calibrate_all(generator, seed_root: int, *, n_cal: int = 500, grid_k=GRID_K, grid_m=GRID_M,
                   grid_rho=GRID_RHO) -> dict:
    """Theta per (K, M, rho) for every combination in the grid (cheap -- 12 combinations at the real grid's
    size -- so every one is calibrated regardless of which cells the cut keeps)."""
    return {
        f"K{K}_M{M}_rho{rho}": calibrate_theta(K, M, rho, generator, seed_root, n_cal=n_cal)
        for K in grid_k for M in grid_m for rho in grid_rho
    }


# ======================================================================================
# Orchestration: one cell, many instances
# ======================================================================================

def _cell_key(cell: dict) -> str:
    parts = [f"K{cell['K']}", f"M{cell['M']}", f"rho{cell['rho']}", f"b{cell['b']}", f"s{cell['s']}"]
    if "tau" in cell:
        parts += [f"tau{cell['tau']}", f"q{cell['q']}"]
    return "_".join(parts)


def _calibration_key(cell: dict) -> str:
    return f"K{cell['K']}_M{cell['M']}_rho{cell['rho']}"


def run_cell(cell: dict, condition: str, generator, seed_root: int, theta: float, n_instances: int) -> list:
    """Every instance's per-arm consensus error, blame and dependence-flag counts for one (cell, condition),
    as a list of plain-dict rows (json-safe except for python bools/floats, which `json.dump` handles) --
    the unit ``plan``/``run``/``rescore`` save and load."""
    rows = []
    for i in range(n_instances):
        inst = generator(cell, condition, i, seed_root)
        reports, sigma, chains = inst["reports"], inst["sigma"], inst["chains"]
        mask = ~np.isnan(reports)
        truth = inst["truth"]
        true_values = np.asarray(truth["true_values"], dtype=float)
        bad = truth["bad"]
        copier = truth["copier"]
        bad_items = np.where(mask[bad])[0]
        true_pair = sorted((bad, copier)) if copier is not None else None

        cons_N = arm_naive(reports, mask)
        cons_I, flagged, ell, s_hat = arm_inferred(reports, mask, theta)
        pair_specs_i = [(p[0], p[1], None) for p in flagged]
        n_honest_flagged = (len(flagged) if true_pair is None
                            else sum(1 for p in flagged if list(p) != true_pair))

        row = {
            "instance": i, "condition": condition,
            "flagged": [list(p) for p in flagged], "s_hat": s_hat,
            "true_pair": true_pair, "n_honest_pairs_flagged": n_honest_flagged,
            "consensus_error": {
                "N_all": consensus_error(cons_N, true_values, sigma, bad_items),
                "I_all": consensus_error(cons_I, true_values, sigma, bad_items),
            },
            "blame": {
                "N": blame_for_arm(reports, mask, cons_N, bad, copier),
                "I": blame_for_arm(reports, mask, cons_I, bad, copier),
            },
        }

        if condition in ("C", "D"):
            copied_items = np.asarray(truth["copied_items"], dtype=int)
            scored = scored_items(truth)
            pair_specs_p = provenance_pairs(chains)
            cons_P = collapse_consensus(reports, mask, pair_specs_p)
            half_rng = p_half_drop_seed(cell, i, seed_root)
            pair_specs_phalf = p_half_pairs(chains, copied_items, half_rng)
            cons_Phalf = collapse_consensus(reports, mask, pair_specs_phalf)
            cons_O = arm_oracle(reports, mask, bad, copier, copied_items)

            for arm, cons in (("N", cons_N), ("I", cons_I), ("P", cons_P), ("P_half", cons_Phalf),
                              ("O", cons_O)):
                row["consensus_error"][arm] = consensus_error(cons, true_values, sigma, scored)
            row["blame"]["P"] = blame_for_arm(reports, mask, cons_P, bad, copier)
            row["blame"]["P_half"] = blame_for_arm(reports, mask, cons_Phalf, bad, copier)
            row["blame"]["O"] = blame_for_arm(reports, mask, cons_O, bad, copier)
            row["n_scored"] = int(len(scored))
            row["n_copied"] = int(len(copied_items))

            # P-half's missing half: the share of the scored items whose chain was dropped this instance.
            kept_items = set()
            for (_, _, items) in pair_specs_phalf:
                kept_items |= items
            missing = set(copied_items.tolist()) - kept_items
            row["p_half_missing_share_of_scored"] = (
                float(len(missing & set(scored.tolist()))) / len(scored) if len(scored) else float("nan"))

            # "Rests on dependent reports": I's own flag (meaningful in D) and P's equivalent (meaningful in
            # C), each against the truth's own oracle-collapse-moves-consensus definition (0.5 sigma, the
            # real sigma -- never the auditor's s-hat estimate).
            truth_flags = truth_rests_on_dependent_reports(reports, mask, bad, copier, copied_items, sigma)
            i_flags = rests_on_dependent_reports(reports, mask, pair_specs_i, s_hat)
            p_flags = rests_on_dependent_reports(reports, mask, pair_specs_p, s_hat)
            row["rests_on_dependent_reports"] = {
                "I": flag_counts(i_flags, truth_flags),
                "P": flag_counts(p_flags, truth_flags),
            }

        rows.append(row)
    return rows


# ======================================================================================
# The plan
# ======================================================================================

def build_plan(*, generator=GENERATOR, seed_root_calibration: int, seed_root_pilot: int, seed_root_run: int,
                n_cal: int = 500, n_pilot: int = PILOT_INSTANCES, n_instances: int = 500,
                grid_k=GRID_K, grid_m=GRID_M, grid_rho=GRID_RHO, grid_b=GRID_B, grid_s=GRID_S,
                grid_tau=GRID_TAU, grid_q=GRID_Q) -> dict:
    """The pre-registration, exactly as the fixture spec (93e08797) and this one fix it:

    1. the full grid's pilots (``n_pilot`` instances per cell, the pilot seed, disjoint from the run's) and
       the cut (kept where the pilot share is between 1.5x chance and 0.9; dropped cells are recorded for
       the sensitivity report, never discarded);
    2. theta per (K, M, rho), from ``n_cal`` A calibration instances on a seed disjoint from the pilots' and
       the run's, pooled over b and s, with the false-flag rate per (b, s);
    3. for each *kept* C/D cell, the ceiling count (N-O and the share off by more than 0.5 sigma) and the
       auditor's pilot detection rate, both read off the same pilot instances the cut already drew -- no
       redraw;
    4. ``n_instances`` (500 at the real grid) and the run seeds, fixed here, before any method runs on them.

    The grid axes default to the fixture spec's real grid; the ``grid_*`` overrides exist only so tests (and
    a labelled smoke) can run this on a handful of cells instead of the real ~500. No reader-model or
    retrieval calls; pure numpy on ``generator``."""
    calibrations = calibrate_all(generator, seed_root_calibration, n_cal=n_cal,
                                 grid_k=grid_k, grid_m=grid_m, grid_rho=grid_rho)

    kept_cells: list = []
    dropped_cells: list = []
    pilot_a: dict = {}
    pilot_cd: dict = {}
    ceiling: dict = {}
    auditor_pilot_detection_by_cell: dict = {}

    for cell in full_a_cells(grid_k=grid_k, grid_m=grid_m, grid_rho=grid_rho, grid_b=grid_b, grid_s=grid_s):
        key = _cell_key(cell)
        result = pilot_a_cell(cell, generator, seed_root_pilot, n_pilot)
        pilot_a[key] = {"share": result["share"], "chance": result["chance"]}
        entry = {"cell": cell, "key": key, "condition": "A", "share": result["share"],
                 "chance": result["chance"]}
        if cut_keeps(result["share"], result["chance"]):
            kept_cells.append({"cell": cell, "key": key, "condition": "A"})
        else:
            dropped_cells.append(entry)

    for cell in full_cd_cells(grid_k=grid_k, grid_m=grid_m, grid_rho=grid_rho, grid_b=grid_b, grid_s=grid_s,
                              grid_tau=grid_tau, grid_q=grid_q):
        key = _cell_key(cell)
        result = pilot_cd_cell(cell, generator, seed_root_pilot, n_pilot)
        pilot_cd[key] = {"share": result["share"], "chance": result["chance"]}
        if cut_keeps(result["share"], result["chance"]):
            kept_cells.append({"cell": cell, "key": key, "condition": "C/D"})
            ceiling[key] = {**ceiling_from_pilot_instances(result["instances"]), "cell": cell,
                           "n_pilot": n_pilot}
            cal_key = _calibration_key(cell)
            theta = calibrations[cal_key]["theta"]
            auditor_pilot_detection_by_cell[key] = auditor_pilot_detection(result["instances"], theta)
        else:
            dropped_cells.append({"cell": cell, "key": key, "condition": "C/D", "share": result["share"],
                                  "chance": result["chance"]})

    return {
        "grid": {"K": list(grid_k), "M": list(grid_m), "rho": list(grid_rho), "b": list(grid_b),
                "s": list(grid_s), "tau": list(grid_tau), "q": list(grid_q)},
        "calibrations": calibrations,
        "pilot": {"n_pilot": n_pilot, "a": pilot_a, "cd": pilot_cd},
        "cells": kept_cells,
        "dropped_cells": dropped_cells,
        "ceiling": ceiling,
        "auditor_pilot_detection": auditor_pilot_detection_by_cell,
        "n_instances": n_instances,
        "n_cal": n_cal,
        "seeds": {"calibration": seed_root_calibration, "pilot": seed_root_pilot, "run": seed_root_run},
    }


def run_plan(plan: dict, *, generator=GENERATOR, n_instances: int | None = None) -> dict:
    """Runs every cell in ``plan`` for the conditions its downstream measures need: A cells run condition A
    once; C/D cells run both C (for P and the P-on-C-equals-O check) and D (for N, I, O and the primary).
    Returns ``{cell_key: {condition: rows}}``, exactly what ``rescore`` consumes."""
    n = n_instances if n_instances is not None else plan["n_instances"]
    seed_root_run = plan["seeds"]["run"]
    results: dict = {}
    for entry in plan["cells"]:
        cell, key, condition = entry["cell"], entry["key"], entry["condition"]
        if condition == "A":
            theta = plan["calibrations"][_calibration_key(cell)]["theta"]
            results[key] = {"A": run_cell(cell, "A", generator, seed_root_run, theta, n)}
        else:
            cal_key = _calibration_key(cell)
            theta = plan["calibrations"][cal_key]["theta"] if cal_key in plan["calibrations"] else float("nan")
            results[key] = {
                "C": run_cell(cell, "C", generator, seed_root_run, theta, n),
                "D": run_cell(cell, "D", generator, seed_root_run, theta, n),
            }
    return results


def summarize(plan: dict, results: dict) -> dict:
    """Turns ``run_plan``'s rows into the primary (S_I, its bootstrap CI and reading), the gap Delta,
    do-no-harm in A (pooled and at the high-bias corner if present), the ceiling check, detection rates, and
    the P-on-C-equals-O / C-and-D-give-identical-N checks."""
    gain_n_minus_i: dict = {}
    gain_n_minus_o: dict = {}
    gain_n_minus_phalf: dict = {}
    err_i_on_d: dict = {}
    err_p_on_c: dict = {}
    gain_i_minus_n_a: dict = {}
    gain_i_minus_n_a_high_bias = None
    false_flag_rate_a_by_cell: dict = {}
    detection_by_cell = {}
    p_equals_o_max_diff = 0.0
    n_identical_c_d = True
    p_half_missing_share: dict = {}
    rests_counts = {"I": {"tp": 0, "fp": 0, "fn": 0}, "P": {"tp": 0, "fp": 0, "fn": 0}}
    by_tau_q: dict = {}
    blame_bad_by_arm: dict = {arm: {} for arm in ("N", "I", "P", "P_half", "O")}
    blame_copier_by_arm: dict = {arm: {} for arm in ("N", "I", "P", "P_half", "O")}

    for entry in plan["cells"]:
        key, condition = entry["key"], entry["condition"]
        cell = entry["cell"]
        cell_results = results.get(key, {})

        if condition == "A":
            rows = cell_results.get("A", [])
            diffs = [r["consensus_error"]["I_all"] - r["consensus_error"]["N_all"] for r in rows]
            gain_i_minus_n_a[key] = diffs
            false_flag_rate_a_by_cell[key] = false_flag_rate_a(rows)
            if (cell.get("K"), cell.get("M"), cell.get("rho"), cell.get("b")) == (6, 60, 0.9, 8.0):
                gain_i_minus_n_a_high_bias = diffs
            for arm in ("N", "I"):
                blame_bad_by_arm[arm][key] = [r["blame"][arm]["bad_first_credit"] for r in rows]
            continue

        rows_c = cell_results.get("C", [])
        rows_d = cell_results.get("D", [])
        n_i = [r["consensus_error"]["N"] - r["consensus_error"]["I"] for r in rows_d
              if not np.isnan(r["consensus_error"]["N"])]
        n_o = [r["consensus_error"]["N"] - r["consensus_error"]["O"] for r in rows_d
              if not np.isnan(r["consensus_error"]["N"])]
        gain_n_minus_i[key] = n_i
        gain_n_minus_o[key] = n_o
        gain_n_minus_phalf[key] = [r["consensus_error"]["N"] - r["consensus_error"]["P_half"] for r in rows_c
                                   if not np.isnan(r["consensus_error"]["N"])]
        err_i_on_d[key] = [r["consensus_error"]["I"] for r in rows_d]
        err_p_on_c[key] = [r["consensus_error"]["P"] for r in rows_c]
        detection_by_cell[key] = detection_rates(rows_d)
        p_half_missing_share[key] = float(np.nanmean(
            [r["p_half_missing_share_of_scored"] for r in rows_c])) if rows_c else float("nan")
        tau_q_key = (cell.get("tau"), cell.get("q"))
        group = by_tau_q.setdefault(tau_q_key, {"n_i": {}, "n_o": {}})
        group["n_i"][key] = n_i
        group["n_o"][key] = n_o

        for row_d in rows_d:
            rests_counts["I"]["tp"] += row_d["rests_on_dependent_reports"]["I"]["tp"]
            rests_counts["I"]["fp"] += row_d["rests_on_dependent_reports"]["I"]["fp"]
            rests_counts["I"]["fn"] += row_d["rests_on_dependent_reports"]["I"]["fn"]
        for row_c in rows_c:
            rests_counts["P"]["tp"] += row_c["rests_on_dependent_reports"]["P"]["tp"]
            rests_counts["P"]["fp"] += row_c["rests_on_dependent_reports"]["P"]["fp"]
            rests_counts["P"]["fn"] += row_c["rests_on_dependent_reports"]["P"]["fn"]

        for arm in ("N", "I", "P", "P_half", "O"):
            blame_bad_by_arm[arm][key] = [r["blame"][arm]["bad_first_credit"] for r in rows_d]
            copier_credits = [r["blame"][arm]["copier_first_credit"] for r in rows_d
                              if r["blame"][arm]["copier_first_credit"] is not None]
            if copier_credits:
                blame_copier_by_arm[arm][key] = copier_credits

        for row_c, row_d in zip(rows_c, rows_d):
            p_err, o_err = row_c["consensus_error"]["P"], row_c["consensus_error"]["O"]
            if not (np.isnan(p_err) and np.isnan(o_err)):
                p_equals_o_max_diff = max(p_equals_o_max_diff, abs(p_err - o_err))
            if row_c["consensus_error"]["N"] != row_d["consensus_error"]["N"] and not (
                    np.isnan(row_c["consensus_error"]["N"]) and np.isnan(row_d["consensus_error"]["N"])):
                n_identical_c_d = False

    by_tau_q_s_i = {
        f"tau{tau}_q{q}": s_i_ratio(group["n_i"], group["n_o"]) for (tau, q), group in by_tau_q.items()
    }
    rests_recall_precision = {
        "I_on_D": recall_precision_from_counts(**rests_counts["I"]),
        "P_on_C": recall_precision_from_counts(**rests_counts["P"]),
    }
    blame_summary = {
        arm: {
            "bad_first_credit": pooled_gain(blame_bad_by_arm[arm]),
            "copier_first_credit": pooled_gain(blame_copier_by_arm[arm]) if blame_copier_by_arm[arm]
            else float("nan"),
        }
        for arm in ("N", "I", "P", "P_half", "O")
    }

    primary = bootstrap_ratio_ci(gain_n_minus_i, gain_n_minus_o)
    primary["reading"] = primary_reading(primary["ci95"])
    delta = gap_delta(err_i_on_d, err_p_on_c)
    ceiling = ceiling_check(gain_n_minus_o)
    dnh_pooled = do_no_harm(gain_i_minus_n_a)
    dnh_high_bias = do_no_harm({"K6_M60_rho0.9_b8": gain_i_minus_n_a_high_bias}) \
        if gain_i_minus_n_a_high_bias is not None else None
    # "Inference at all": I against N on D, paired; "the auditor helps" if the interval excludes 0 in
    # I's favour (its lower end is above 0).
    inference_at_all = bootstrap_pooled_mean_ci(gain_n_minus_i)
    inference_at_all["auditor_helps"] = bool(inference_at_all["ci95"][0] > 0.0)

    return {
        "primary": primary,
        "gap_delta": delta,
        "ceiling": ceiling,
        "do_no_harm": {"pooled": dnh_pooled, "high_bias_corner": dnh_high_bias},
        "inference_at_all": inference_at_all,
        "detection": {"D": detection_by_cell, "A_false_flag_rate": false_flag_rate_a_by_cell},
        "blame": blame_summary,
        "rests_on_dependent_reports": rests_recall_precision,
        "by_tau_q": {"s_i": by_tau_q_s_i},
        "per_cell": {
            "s_i": per_cell_ratios(gain_n_minus_i, gain_n_minus_o),
            "s_p_half": per_cell_ratios(gain_n_minus_phalf, gain_n_minus_o),
            "p_half_missing_share_of_scored": p_half_missing_share,
        },
        "checks": {
            "p_on_c_equals_o_max_abs_diff": p_equals_o_max_diff,
            "n_identical_between_c_and_d": n_identical_c_d,
        },
    }


# ======================================================================================
# CLI
# ======================================================================================

DEFAULT_SEED_CALIBRATION = 2026112208
DEFAULT_SEED_PILOT = 2026112209
DEFAULT_SEED_RUN = 2026112210


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = build_plan(
        seed_root_calibration=args.seed_calibration, seed_root_pilot=args.seed_pilot,
        seed_root_run=args.seed_run, n_cal=args.n_cal, n_pilot=args.n_pilot, n_instances=args.n_instances)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=1, sort_keys=True)
    summary = {k: v for k, v in plan.items() if k not in ("cells", "dropped_cells")}
    summary["n_kept_cells"] = len(plan["cells"])
    summary["n_dropped_cells"] = len(plan["dropped_cells"])
    summary["kept_by_condition"] = {
        condition: sum(1 for e in plan["cells"] if e["condition"] == condition) for condition in ("A", "C/D")
    }
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    results = run_plan(plan, n_instances=args.n_instances)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=1, sort_keys=True)
    print(json.dumps({"n_cells_run": len(results)}, indent=1))
    return 0


def _cmd_rescore(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)
    summary = summarize(plan, results)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=1, sort_keys=True)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="North-star test 7: kept provenance against inferred independence")
    sub = parser.add_subparsers(dest="mode", required=True)

    plan_parser = sub.add_parser("plan", help="calibrate theta and count the ceiling; no model calls")
    plan_parser.add_argument("--seed-calibration", type=int, default=DEFAULT_SEED_CALIBRATION)
    plan_parser.add_argument("--seed-pilot", type=int, default=DEFAULT_SEED_PILOT)
    plan_parser.add_argument("--seed-run", type=int, default=DEFAULT_SEED_RUN)
    plan_parser.add_argument("--n-cal", type=int, default=500)
    plan_parser.add_argument("--n-pilot", type=int, default=PILOT_INSTANCES)
    plan_parser.add_argument("--n-instances", type=int, default=500)
    plan_parser.add_argument("--out", default="plan.json")
    plan_parser.set_defaults(func=_cmd_plan)

    run_parser = sub.add_parser("run", help="run every cell's instances through the arms; no model calls")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--n-instances", type=int, default=None, help="override the plan's N, for a smoke")
    run_parser.add_argument("--out")
    run_parser.set_defaults(func=_cmd_run)

    rescore_parser = sub.add_parser("rescore", help="recompute the summary from a saved run; no model calls")
    rescore_parser.add_argument("--plan", required=True)
    rescore_parser.add_argument("--results", required=True)
    rescore_parser.add_argument("--out")
    rescore_parser.set_defaults(func=_cmd_rescore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
