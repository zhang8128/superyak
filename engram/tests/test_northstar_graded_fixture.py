"""The graded-blame fixture (docs/superpowers/specs/2026-11-22-graded-blame-fixture-design.md, approved at 93e08797),
for north-star test 7 (Serenity, `serenity/north-star-test-7` 79ebcd91), with the interface she proposed in all hands
d9c5f051."""
from __future__ import annotations

import math

import numpy as np
import pytest

from experiments.northstar.graded_fixture import SIGMA, generate

CELL = {"K": 5, "M": 40, "rho": 0.5, "b": 4, "s": 0.5, "tau": 1.0, "q": 0.5}


def reported(inst):
    return ~np.isnan(inst["reports"])


@pytest.mark.parametrize("index", range(20))
def test_c_and_d_have_identical_reports_and_differ_only_in_chains(index):
    c, d = generate(CELL, "C", index), generate(CELL, "D", index)
    assert np.array_equal(c["reports"], d["reports"], equal_nan=True)
    assert all(x is None for x in d["chains"].ravel())
    copier, bad = c["truth"]["copier"], c["truth"]["bad"]
    named = [(k, i) for k in range(CELL["K"]) for i in range(CELL["M"]) if c["chains"][k, i] is not None]
    assert named == [(copier, i) for i in c["truth"]["copied_items"]]
    assert all(c["chains"][copier, i] == bad for i in c["truth"]["copied_items"])


@pytest.mark.parametrize("index", range(20))
def test_a_shares_the_base_and_differs_only_on_the_copied_reports(index):
    a, c = generate(CELL, "A", index), generate(CELL, "C", index)
    assert a["truth"]["copier"] is None and a["truth"]["copied_items"] == []
    assert a["truth"]["bad"] == c["truth"]["bad"] and a["truth"]["biased_items"] == c["truth"]["biased_items"]
    assert np.array_equal(reported(a), reported(c))
    differ = reported(a) & (a["reports"] != c["reports"])  # NaN never equals itself: compare reported cells only
    diff = {(int(k), int(i)) for k, i in zip(*np.where(differ))}
    assert diff <= {(c["truth"]["copier"], i) for i in c["truth"]["copied_items"]}


@pytest.mark.parametrize("cell", [CELL, {**CELL, "K": 4, "M": 20, "rho": 0.5}, {**CELL, "K": 6, "M": 60, "rho": 0.9}])
@pytest.mark.parametrize("index", range(10))
def test_every_item_has_two_reports_and_every_source_five(cell, index):
    inst = generate(cell, "C", index)
    seen = reported(inst)
    assert seen.sum(axis=0).min() >= 2 and seen.sum(axis=1).min() >= 5
    assert inst["meta"]["realised_density"] == pytest.approx(seen.mean())


@pytest.mark.parametrize("index", range(10))
def test_the_bad_source_biases_its_share_by_b_sigma_with_one_sign(index):
    inst = generate(CELL, "A", index, _noise=False)
    bad, truth = inst["truth"]["bad"], inst["truth"]["true_values"]
    own = [i for i in range(CELL["M"]) if not math.isnan(inst["reports"][bad, i])]
    assert len(inst["truth"]["biased_items"]) == math.ceil(CELL["s"] * len(own))
    shifts = {round(inst["reports"][bad, i] - truth[i], 12) for i in inst["truth"]["biased_items"]}
    assert len(shifts) == 1 and abs(shifts.pop()) == pytest.approx(CELL["b"] * SIGMA)
    honest = [k for k in range(CELL["K"]) if k != bad]
    for k in honest:
        for i in range(CELL["M"]):
            if not math.isnan(inst["reports"][k, i]):
                assert inst["reports"][k, i] == pytest.approx(truth[i])


@pytest.mark.parametrize("index", range(10))
def test_the_copier_repeats_the_bad_report_on_its_copied_share(index):
    inst = generate(CELL, "C", index, _noise=False)
    bad, copier = inst["truth"]["bad"], inst["truth"]["copier"]
    shared = [i for i in range(CELL["M"]) if reported(inst)[bad, i] and reported(inst)[copier, i]]
    assert len(inst["truth"]["copied_items"]) == math.ceil(CELL["q"] * len(shared))
    for i in inst["truth"]["copied_items"]:
        assert inst["reports"][copier, i] == inst["reports"][bad, i]
        others = [k for k in range(CELL["K"]) if k not in (bad, copier) and reported(inst)[k, i]]
        assert inst["truth"]["honest_counts_on_copied"][i] == len(others)


def test_the_copier_adds_its_own_noise_tau_sigma():
    diffs = []
    for index in range(200):
        inst = generate({**CELL, "tau": 1.5}, "C", index)
        bad, copier = inst["truth"]["bad"], inst["truth"]["copier"]
        diffs += [inst["reports"][copier, i] - inst["reports"][bad, i] for i in inst["truth"]["copied_items"]]
    assert np.std(diffs) == pytest.approx(1.5 * SIGMA, rel=0.1)


def test_it_is_deterministic_and_instances_differ():
    one, again, other = generate(CELL, "D", 3), generate(CELL, "D", 3), generate(CELL, "D", 4)
    assert np.array_equal(one["reports"], again["reports"], equal_nan=True)
    assert not np.array_equal(one["reports"], other["reports"], equal_nan=True)
    assert generate(CELL, "D", 3, seed_root=1)["meta"]["seeds"] != one["meta"]["seeds"]


def test_an_instance_is_frozen():
    inst = generate(CELL, "C", 0)
    with pytest.raises(TypeError):
        inst["sigma"] = 1
    with pytest.raises(ValueError):
        inst["reports"][0, 0] = 1.0


def test_refusals():
    with pytest.raises(ValueError, match="condition"):
        generate(CELL, "U", 0)  # U feeds test 6's property check only (spec revision 3)
    with pytest.raises(ValueError, match="K"):
        generate({**CELL, "K": 3}, "C", 0)  # C and D need K of 4 or more
    with pytest.raises(ValueError, match="tau"):
        generate({k: v for k, v in CELL.items() if k != "tau"}, "C", 0)
