"""North-star test 4's policy half, tested on hand-built records and one trivial world written here (never the world
half's code, which these tests don't import or read)."""
from __future__ import annotations

import numpy as np
import pytest

from experiments.northstar.test4_policies import (POLICIES, SEEDS, adaptive_content, adaptive_name, fixed,
                                                  random)


def entry(turn, state, name, content=None, verdict="fail", says=None, observation=None):
    content = content or f"c-{name}"
    says = says or {"pass": "worked", "fail": "failed"}[verdict]
    return {"turn": turn, "state": state, "name": name, "content": content, "verdict": verdict,
            "summary": {"approach": content, "says": says}, "observation": observation}


def opt(name, content=None):
    return {"name": name, "content": content or f"c-{name}"}


ABC = [opt("a"), opt("b"), opt("c")]


# --- fixed -------------------------------------------------------------------------------------------------------

def test_fixed_takes_the_first_option_with_the_fewest_tries_by_name():
    assert fixed([], ABC, 0) == (0, [])
    record = [entry(1, "L0", "a"), entry(2, "L0", "b")]
    assert fixed(record, ABC, 0) == (2, [])
    record.append(entry(3, "L0", "c"))
    assert fixed(record, ABC, 0) == (0, [])                       # round robin: back to the top


def test_fixed_counts_by_name_in_the_whole_record_and_ignores_verdicts_and_seeds():
    record = [entry(1, "L1", "a", verdict="pass"), entry(2, "L1", "a")]
    assert fixed(record, ABC, 0) == fixed(record, ABC, 7) == (1, [])
    # tries in another state count too: per state, `a` would be untried at L1
    assert fixed([entry(1, "L0", "a"), entry(2, "L1", "b", verdict="pass")], ABC, 0) == (2, [])
    # a renamed idea is untried to fixed: same content, new name
    assert fixed([entry(1, "L0", "a")], [opt("a"), opt("z", "c-a")], 0) == (1, [])


# --- random ------------------------------------------------------------------------------------------------------

def test_random_builds_its_generator_from_the_seed_and_the_record_length():
    record = [entry(1, "L0", "a")]
    expect = int(np.random.default_rng([3, 1]).integers(3))
    assert random(record, ABC, 3) == (expect, [])
    draws = {random([entry(t, "L0", "a") for t in range(1, n + 1)], ABC, 3)[0] for n in range(40)}
    assert draws == {0, 1, 2}                                     # not the same draw every turn (review 1, V3)


def test_random_is_uniform_and_raises_no_flags():
    counts = np.bincount([random([], ABC, s)[0] for s in range(3000)], minlength=3)
    assert counts.min() > 900
    assert random([entry(1, "C1", "a", says="worked")], ABC, 0)[1] == []


# --- adaptive: counts, Thompson ----------------------------------------------------------------------------------

def test_adaptive_counts_verdicts_never_summaries():
    misled = [entry(t, "L0", "a", verdict="fail", says="worked") for t in range(1, 30)]
    picks = [adaptive_name(misled, [opt("a"), opt("b")], s)[0] for s in SEEDS]
    assert picks.count(1) >= 18                                   # 29 fails on a: b wins nearly always


def test_thompson_draws_one_beta_per_option_in_order_from_its_own_generator():
    record = [entry(1, "L1", "b", verdict="pass"), entry(2, "L1", "c")]
    rng = np.random.default_rng([5, 2, 1])
    draws = [rng.beta(1, 1), rng.beta(2, 1), rng.beta(1, 2)]
    assert adaptive_name(record, ABC, 5)[0] == int(np.argmax(draws))


def test_by_name_and_by_content_key_differently_on_a_renamed_idea():
    record = [entry(t, "L0", "a", content="x") for t in range(1, 40)]
    offered = [opt("fresh", "x"), opt("other", "y")]
    by_name = [adaptive_name(record, offered, s)[0] for s in SEEDS]
    by_content = [adaptive_content(record, offered, s)[0] for s in SEEDS]
    assert by_name.count(0) >= 6                                  # a fresh name is a fresh arm
    assert by_content.count(0) == 0                               # its content has failed 39 times


# --- flags -------------------------------------------------------------------------------------------------------

def test_cycle_on_an_arrival_after_the_first_and_not_on_a_failed_step_that_stays():
    stay = [entry(1, "L0", "a"), entry(2, "L0", "b")]
    assert adaptive_name(stay, ABC, 0)[1] == []                   # a failed step stays: no arrival
    loop = [entry(1, "L1", "k", verdict="pass"), entry(2, "C1", "lure", verdict="pass"),
            entry(3, "C2", "lure", verdict="pass"), entry(4, "C3", "lure", verdict="pass"),
            entry(5, "L1", "lure", verdict="pass")]
    assert {"cycle": "L1"} in adaptive_name(loop, ABC, 0)[1]
    assert not any("cycle" in f for f in adaptive_name(loop[:4], ABC, 0)[1])
    assert {"cycle": "L1"} not in adaptive_name(loop + [entry(6, "L1", "x")], ABC, 0)[1]   # only on the arrival


def test_the_start_is_the_first_arrival_at_L0():
    back = [entry(1, "L1", "k", verdict="pass"), entry(2, "L0", "back", verdict="pass")]
    assert {"cycle": "L0"} in adaptive_content(back, ABC, 0)[1]


def test_contradiction_and_premise_are_raised_once_at_the_call_just_after_their_turn():
    record = [entry(1, "L0", "a", verdict="fail", says="worked")]
    assert {"contradiction": 1} in adaptive_name(record, ABC, 0)[1]
    record.append(entry(2, "L0", "b"))
    assert not any("contradiction" in f for f in adaptive_name(record, ABC, 0)[1])
    obs = record + [entry(3, "L2", "k", verdict="pass", observation={"invalidates": ["c-k"]})]
    assert {"premise": 3} in adaptive_content(obs, ABC, 0)[1]
    assert not any("premise" in f for f in adaptive_content(obs + [entry(4, "L2", "a")], ABC, 0)[1])


def test_premise_drops_the_named_contents_verdicts_up_to_its_own_turn_and_keeps_later_ones():
    from experiments.northstar.test4_policies import _counts
    record = [entry(1, "L1", "k", verdict="pass"), entry(2, "L2", "k", verdict="pass"),
              entry(3, "L3", "k", verdict="pass", observation={"invalidates": ["c-k"]}),
              entry(4, "L3", "k", verdict="fail")]
    assert _counts(record, "name") == ({}, {"k": 1})
    assert _counts(record, "content") == ({}, {"c-k": 1})


def test_repeat_is_raised_by_content_only_for_a_content_tried_under_another_name():
    record = [entry(1, "L0", "a", content="x")]
    offered = [opt("b", "x"), opt("a", "x"), opt("c", "y")]
    assert adaptive_content(record, offered, 0)[1] == [{"repeat": "x"}]
    assert not any("repeat" in f for f in adaptive_name(record, offered, 0)[1])
    assert not any("repeat" in f for f in adaptive_content(record, [opt("a", "x")], 0)[1])


# --- every policy, on a trivial world written here -----------------------------------------------------------------

def chain(depth, k, seed):
    """A trivial chain written for these tests: one key per level advances, the rest fail and stay."""
    rng = np.random.default_rng(seed)
    levels = []
    for _ in range(depth):
        names = [f"n{j}" for j in rng.permutation(k)]
        levels.append({"options": [opt(n) for n in names], "key": names[0 if rng.random() < 0.5 else -1]})
    return levels


def run(policy, levels, seed, budget):
    record, level = [], 0
    for turn in range(1, budget + 1):
        state = f"L{level}"
        options = levels[level]["options"]
        index, flags = policy(record, options, seed)
        assert 0 <= index < len(options) and isinstance(flags, list)
        chosen = options[index]
        passed = chosen["name"] == levels[level]["key"]
        level += passed
        state = "G" if level == len(levels) else f"L{level}"
        record.append({"turn": turn, "state": state, "name": chosen["name"], "content": chosen["content"],
                       "verdict": "pass" if passed else "fail",
                       "summary": {"approach": chosen["content"], "says": "worked" if passed else "failed"},
                       "observation": None})
        if state == "G":
            return turn
    return None


@pytest.mark.parametrize("name", sorted(POLICIES))
def test_every_policy_recovers_in_a_trivial_world_and_is_deterministic(name):
    policy = POLICIES[name]
    levels = chain(4, 3, 11)
    turns = [run(policy, levels, s, 2 * 4 * 3) for s in SEEDS]
    assert sum(t is not None for t in turns) >= 18
    assert turns == [run(policy, levels, s, 2 * 4 * 3) for s in SEEDS]


def test_an_empty_option_list_is_refused():
    for policy in POLICIES.values():
        with pytest.raises(ValueError):
            policy([], [], 0)
