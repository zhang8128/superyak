"""North-star test 4, stage A: the runner and scorer, pinned to their definitions.

The fake halves here are built only from "The contract (stage A)". A world has
options(state), step(state, approach), recovered(state) and budget. The world
half exports worlds(), named and false_named, and the policy half exports
fixed, random, adaptive_name and adaptive_content, each mapping (record,
options, seed) to (index, flags). Nothing here knows the real halves. Expected
values come from the definitions in "Stage A", computed here independently of
the runner.
"""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest

from experiments.northstar import test4_runner as t4

# The spec's words, restated so the runner's copies are checked against the
# text rather than against themselves.
CONTRACT_TRAP_FLAG = {1: "cycle", 2: "repeat", 3: "contradiction", 4: "premise"}
CONTRACT_POLICIES = ("fixed", "random", "adaptive_name", "adaptive_content")
CONTRACT_SEEDS = list(range(20))
STAGE_A_PAIRS = [
    ("adaptive_name", "fixed"),
    ("adaptive_name", "random"),
    ("adaptive_content", "fixed"),
    ("adaptive_content", "random"),
    ("adaptive_name", "adaptive_content"),
]


def bootstrap_by_definition(differences: np.ndarray) -> tuple[float, float]:
    """10,000 resamples of worlds from a fresh default_rng(20261130), the
    linear percentile interval at 2.5% and 97.5%. Drawn with choice and cut
    with percentile: other calls than the runner's, the same definition."""
    rng = np.random.default_rng(20261130)
    rows = rng.choice(len(differences), size=(10_000, len(differences)), replace=True)
    means = np.array([differences[row].mean() for row in rows])
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


# ------------------------------------------------------------ small fakes


def entry_for(state, name, content, verdict="fail", observation=None):
    says = "worked" if verdict == "pass" else "failed"
    return {
        "state": state,
        "name": name,
        "content": content,
        "verdict": verdict,
        "summary": {"approach": content, "says": says},
        "observation": observation,
    }


class TableWorld:
    """A world from a table: state -> [(name, content, next state)]."""

    def __init__(self, table, recovered=(), budget=5, seed=0):
        self.table = table
        self.recovered_states = set(recovered)
        self.budget = budget
        self.seed = seed
        self.steps = []

    def options(self, state):
        return [{"name": name, "content": content} for name, content, _ in self.table[state]]

    def entry(self, state, name, content, nxt):
        return entry_for(nxt, name, content, "pass" if nxt in self.recovered_states else "fail")

    def step(self, state, approach):
        self.steps.append((state, dict(approach)))
        for name, content, nxt in self.table[state]:
            if name == approach["name"]:
                return nxt, self.entry(state, name, content, nxt)
        raise AssertionError(f"no {approach!r} in {state}")

    def recovered(self, state):
        return state in self.recovered_states


LOOP = {
    "L0": [("a", "ca", "L1"), ("z", "cz", "Z")],
    "L1": [("b", "cb", "L2"), ("back", "cback", "L0")],
    "L2": [("c", "cc", "L1"), ("d", "cd", "G")],
    "G": [("e", "ce", "G")],
    "Z": [("z2", "cz", "Z2")],
    "Z2": [("z3", "other", "Z3")],
    "Z3": [("z4", "cz", "Z3")],
}


class Script:
    """A policy that takes options by name, one per call, and raises the flags
    scripted for the call made with a record of each length."""

    def __init__(self, names, flags=None):
        self.names = list(names)
        self.flags = dict(flags or {})
        self.calls = []

    def __call__(self, record, options, seed):
        self.calls.append({"record": json.loads(json.dumps(record)), "options": options, "seed": seed})
        made_with = len(record)
        wanted = self.names[min(made_with, len(self.names) - 1)]
        return [o["name"] for o in options].index(wanted), self.flags.get(made_with, [])


# ------------------------------------------------------------------ one run


def test_the_first_call_gets_an_empty_record_the_L0_options_and_the_seed():
    world = TableWorld(LOOP, budget=1)
    policy = Script(["a"])
    t4.run_one(world, policy, 7)
    assert policy.calls == [{"record": [], "options": world.options("L0"), "seed": 7}]


def test_each_call_gets_the_record_so_far_and_its_last_states_options():
    world = TableWorld(LOOP, budget=4)
    policy = Script(["a", "b", "c", "b"])
    run = t4.run_one(world, policy, 3)
    assert [e["state"] for e in run.record] == ["L1", "L2", "L1", "L2"]
    for made_with, call in enumerate(policy.calls):
        assert call["record"] == run.record[:made_with]
        state = run.record[made_with - 1]["state"] if made_with else "L0"
        assert call["options"] == world.options(state)
        assert call["seed"] == 3


def test_the_runner_writes_turn_from_one_over_any_world_turn():
    class TurnWritingWorld(TableWorld):
        def entry(self, state, name, content, nxt):
            return {**super().entry(state, name, content, nxt), "turn": 99}

    run = t4.run_one(TurnWritingWorld(LOOP, budget=3), Script(["a", "b", "c"]), 0)
    assert [e["turn"] for e in run.record] == [1, 2, 3]
    assert list(run.record[0]) == ["turn", "state", "name", "content", "verdict", "summary", "observation"]


def test_a_run_stops_at_the_first_turn_whose_state_passes():
    world = TableWorld(LOOP, recovered={"L2", "G"}, budget=10)
    policy = Script(["a", "b", "d", "e"])
    run = t4.run_one(world, policy, 0)
    assert (run.recovered, run.turns_to_recovery, run.turns_used) == (True, 2, 2)
    assert len(policy.calls) == 2 and len(world.steps) == 2


def test_the_start_is_not_a_turn_so_a_recovered_L0_is_reached_by_a_step():
    world = TableWorld(LOOP, recovered={"L0"}, budget=5)
    run = t4.run_one(world, Script(["a", "back"]), 0)
    assert (run.recovered, run.turns_to_recovery) == (True, 2)
    assert [e["state"] for e in run.record] == ["L1", "L0"]


def test_the_budget_bounds_a_run():
    world = TableWorld(LOOP, budget=3)
    policy = Script(["a", "b", "c"])
    run = t4.run_one(world, policy, 0)
    assert (run.recovered, run.turns_to_recovery, run.turns_used) == (False, None, 3)
    assert len(policy.calls) == 3
    empty = t4.run_one(TableWorld(LOOP, budget=0), Script(["a"]), 0)
    assert (empty.record, empty.flags_per_call, empty.recovered) == ([], [], False)


def test_flags_per_call_i_holds_the_flags_of_the_call_made_with_a_record_of_length_i():
    flags = {i: [{"premise": i}, {"cycle": f"s{i}"}] for i in range(6)}
    run = t4.run_one(TableWorld(LOOP, budget=4), Script(["a", "b", "c", "b"], flags), 0)
    assert run.flags_per_call == [flags[i] for i in range(4)]
    # No call after the last turn: the call with a record of length 4 never happens.
    assert len(run.flags_per_call) == len(run.record) == 4
    stopped = t4.run_one(TableWorld(LOOP, recovered={"L2"}, budget=9), Script(["a", "b"], flags), 0)
    assert stopped.flags_per_call == [flags[0], flags[1]]


def test_distinct_contents_counts_contents_not_names():
    run = t4.run_one(TableWorld(LOOP, budget=4), Script(["z", "z2", "z3", "z4"]), 0)
    assert [e["name"] for e in run.record] == ["z", "z2", "z3", "z4"]
    assert (run.turns_used, run.distinct_contents) == (4, 2)


def test_a_policy_cannot_change_the_record_or_the_worlds_options():
    world = TableWorld(LOOP, budget=3)
    seen = []

    def vandal(record, options, seed):
        seen.append(json.loads(json.dumps(record)))
        for entry in record:
            entry["verdict"] = "pass"
            entry["summary"]["says"] = "worked"
        record.append({"turn": 0})
        options.reverse()
        options[0]["content"] = "forged"
        return 0, []

    run = t4.run_one(world, vandal, 0)
    assert [e["verdict"] for e in run.record] == ["fail", "fail", "fail"]
    assert seen[1] == run.record[:1] and seen[2] == run.record[:2]
    assert world.options("L0")[0] == {"name": "a", "content": "ca"}


def test_flags_change_nothing_in_the_world():
    quiet = t4.run_one(TableWorld(LOOP, budget=4), Script(["a", "b", "c", "b"]), 0)
    flagged = t4.run_one(
        TableWorld(LOOP, budget=4),
        Script(["a", "b", "c", "b"], {i: [{"cycle": "L1"}, {"repeat": "ca"}] for i in range(4)}),
        0,
    )
    assert quiet.record == flagged.record


def test_a_numpy_index_and_turn_are_whole_numbers():
    def numpy_policy(record, options, seed):
        return np.int64(0), [{"contradiction": np.int64(len(record))}]

    run = t4.run_one(TableWorld(LOOP, budget=2), numpy_policy, 0)
    assert run.flags_per_call == [[{"contradiction": 0}], [{"contradiction": 1}]]
    assert type(run.flags_per_call[1][0]["contradiction"]) is int


def answer_policy(answer):
    return lambda record, options, seed: answer


@pytest.mark.parametrize(
    "answer",
    [
        (2, []),  # past the two options in L0
        (-1, []),
        (True, []),
        ("0", []),
        0,
        (0, [], []),
        (0, {"cycle": "L0"}),
        (0, [{"cycle": "L0", "repeat": "ca"}]),
        (0, [{"loop": "L0"}]),
        (0, [{"repeat": 3}]),
        (0, [{"cycle": None}]),
        (0, [{"contradiction": "1"}]),
        (0, [{"premise": True}]),
        (0, [{"premise": 1.0}]),
    ],
)
def test_the_runner_refuses_a_policy_answer_outside_the_exact_forms(answer):
    with pytest.raises(t4.ContractError):
        t4.run_one(TableWorld(LOOP, budget=1), answer_policy(answer), 0)


ENTRY_BREAKS = {
    "wrong name": lambda e: {**e, "name": "other"},
    "wrong content": lambda e: {**e, "content": "other"},
    "missing observation": lambda e: {k: v for k, v in e.items() if k != "observation"},
    "extra key": lambda e: {**e, "solution": "d"},
    "verdict word": lambda e: {**e, "verdict": "ok"},
    "summary approach": lambda e: {**e, "summary": {"approach": "other", "says": "failed"}},
    "summary says": lambda e: {**e, "summary": {"approach": e["content"], "says": "maybe"}},
    "summary extra": lambda e: {**e, "summary": {**e["summary"], "why": "x"}},
    "observation string": lambda e: {**e, "observation": {"invalidates": "ca"}},
    "observation list": lambda e: {**e, "observation": ["ca"]},
    "observation key": lambda e: {**e, "observation": {"invalidates": ["ca"], "also": 1}},
    "state not a string": lambda e: {**e, "state": 1},
}


@pytest.mark.parametrize("break_entry", ENTRY_BREAKS.values(), ids=ENTRY_BREAKS.keys())
def test_the_runner_refuses_an_entry_outside_the_records_form(break_entry):
    class BrokenWorld(TableWorld):
        def entry(self, state, name, content, nxt):
            return break_entry(super().entry(state, name, content, nxt))

    with pytest.raises(t4.ContractError):
        t4.run_one(BrokenWorld(LOOP, budget=1), Script(["a"]), 0)


def test_an_observation_and_a_disagreeing_summary_pass_through_as_written():
    class TrappedSummaryWorld(TableWorld):
        def entry(self, state, name, content, nxt):
            entry = super().entry(state, name, content, nxt)
            return {**entry, "summary": {"approach": content, "says": "worked"}, "observation": {"invalidates": ["ca"]}}

    run = t4.run_one(TrappedSummaryWorld(LOOP, budget=1), Script(["a"]), 0)
    assert run.record[0]["verdict"] == "fail"
    assert run.record[0]["summary"] == {"approach": "ca", "says": "worked"}
    assert run.record[0]["observation"] == {"invalidates": ["ca"]}


def test_the_runner_refuses_a_world_outside_its_forms():
    class NextStateDiffers(TableWorld):
        def step(self, state, approach):
            nxt, entry = super().step(state, approach)
            return "elsewhere", entry

    class ExtraOptionKey(TableWorld):
        def options(self, state):
            return [{**o, "good": True} for o in super().options(state)]

    class StringCheck(TableWorld):
        def recovered(self, state):
            return "no"

    class NoBudget(TableWorld):
        budget = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            del self.budget

    for world in (NextStateDiffers(LOOP), ExtraOptionKey(LOOP), StringCheck(LOOP), NoBudget(LOOP)):
        with pytest.raises(t4.ContractError):
            t4.run_one(world, Script(["a"]), 0)


def test_named_must_answer_true_false_or_none():
    run = t4.run_one(TableWorld(LOOP, budget=1), Script(["a"]), 0)
    for answer in (True, False, None):
        half = types.SimpleNamespace(named=lambda w, r, f, a=answer: a)
        assert t4.apply_named(half, None, run) is answer
    with pytest.raises(t4.ContractError):
        t4.apply_named(types.SimpleNamespace(named=lambda w, r, f: 1), None, run)
    with pytest.raises(t4.ContractError):
        t4.apply_false_named(types.SimpleNamespace(false_named=lambda w, r, f: None), None, run)


def test_named_gets_the_world_the_record_and_flags_per_call_as_copies():
    world = TableWorld(LOOP, budget=2)
    run = t4.run_one(world, Script(["a", "b"], {0: [{"cycle": "L0"}], 1: [{"premise": 1}]}), 0)
    seen = {}

    def named(w, record, flags_per_call):
        seen.update(world=w, record=json.loads(json.dumps(record)), flags=json.loads(json.dumps(flags_per_call)))
        record.clear()
        flags_per_call.clear()
        return True

    t4.apply_named(types.SimpleNamespace(named=named), world, run)
    assert seen == {"world": world, "record": run.record, "flags": [[{"cycle": "L0"}], [{"premise": 1}]]}
    assert len(run.record) == 2 and len(run.flags_per_call) == 2


def test_the_trap_to_flag_map_is_the_contracts():
    assert t4.TRAP_FLAG == CONTRACT_TRAP_FLAG
    assert t4.POLICY_NAMES == CONTRACT_POLICIES
    assert list(t4.POLICY_SEEDS) == CONTRACT_SEEDS
    flags = [[{"repeat": "x"}], [], [{"premise": 2}]]
    assert [t4.trap_flag_raised(trap, flags) for trap in (1, 2, 3, 4)] == [False, True, False, True]


# ------------------------------------------------------------ worlds, twins


class Bare:
    def __init__(self, seed):
        self.seed = seed


def eight_hundred(*, seeds=True, dkw=lambda j: (j % 2, 3, 1), twin_order=lambda j: 37 * j % 100):
    def worlds():
        for trap in (1, 2, 3, 4):
            for j in range(100):
                d, k, w = dkw(j)
                yield {"world": Bare(1000 * trap + j if seeds else None), "trap": trap, "D": d, "k": k, "w": w,
                       "form": "trapped"}
        for trap in (4, 3, 2, 1):
            for i in range(100):
                j = twin_order(i)
                d, k, w = dkw(j)
                yield {"world": Bare(1000 * trap + j if seeds else None), "trap": trap, "D": d, "k": k, "w": w,
                       "form": "twin"}

    return types.SimpleNamespace(worlds=worlds)


def test_each_trapped_world_joins_the_twin_with_its_trap_D_k_w_and_seed():
    pairs = t4.collect_worlds(eight_hundred())
    assert sorted(pairs) == [1, 2, 3, 4]
    for trap, joined in pairs.items():
        assert [p.index for p in joined] == list(range(100))
        assert [p.trapped.seed for p in joined] == [1000 * trap + j for j in range(100)]
        assert all(p.twin.seed == p.trapped.seed and p.twin is not p.trapped for p in joined)
        assert all(p.seed == p.trapped.seed and p.D == p.trapped.seed % 2 for p in joined)


def test_without_seeds_twins_join_on_trap_D_k_w_only_when_that_is_one_to_one():
    pairs = t4.collect_worlds(eight_hundred(seeds=False, dkw=lambda j: (j, j % 3, j % 5)))
    assert all(p.D == p.index for joined in pairs.values() for p in joined)
    with pytest.raises(t4.ContractError, match="one-to-one"):
        t4.collect_worlds(eight_hundred(seeds=False))


def test_collect_worlds_refuses_anything_but_100_pairs_in_each_of_4_traps():
    whole = list(eight_hundred().worlds())
    short = types.SimpleNamespace(worlds=lambda: iter(whole[:-1]))
    with pytest.raises(t4.ContractError, match="799"):
        t4.collect_worlds(short)
    doubled = whole[:-1] + [dict(whole[-2])]
    with pytest.raises(t4.ContractError, match="one-to-one"):
        t4.collect_worlds(types.SimpleNamespace(worlds=lambda: iter(doubled)))
    bad_trap = [dict(item, trap=5) if n == 0 else item for n, item in enumerate(whole)]
    with pytest.raises(t4.ContractError, match="trap"):
        t4.collect_worlds(types.SimpleNamespace(worlds=lambda: iter(bad_trap)))
    bad_form = [dict(item, form="untrapped") if n == 0 else item for n, item in enumerate(whole)]
    with pytest.raises(t4.ContractError, match="form"):
        t4.collect_worlds(types.SimpleNamespace(worlds=lambda: iter(bad_form)))


def test_a_world_item_reads_as_a_mapping_a_six_tuple_or_attributes():
    world = Bare(5)
    as_map = t4.unpack_item({"world": world, "trap": 2, "D": 1, "k": 2, "w": 3, "form": "twin"})
    as_tuple = t4.unpack_item((world, 2, 1, 2, 3, "twin"))
    carrier = types.SimpleNamespace(seed=5, trap=2, D=1, k=2, w=3, form="twin")
    as_attrs = t4.unpack_item(carrier)
    for item in (as_map, as_tuple):
        assert (item.world, item.trap, item.D, item.k, item.w, item.form, item.seed) == (world, 2, 1, 2, 3, "twin", 5)
    assert (as_attrs.world, as_attrs.trap, as_attrs.form, as_attrs.seed) == (carrier, 2, "twin", 5)
    with pytest.raises(t4.ContractError):
        t4.unpack_item((world, 2, 1, 2, "twin"))


# ------------------------------------------------------------------ scoring


def test_a_recovery_rate_is_over_the_20_seeds():
    assert t4.recovery_rate([True] * 5 + [False] * 15) == 0.25
    with pytest.raises(ValueError):
        t4.recovery_rate([True] * 19)
    with pytest.raises(ValueError):
        t4.recovery_rate([True] * 40)


def test_the_trap_effect_is_the_trapped_rate_minus_the_twins():
    assert t4.trap_effect([True] * 5 + [False] * 15, [True] * 15 + [False] * 5) == pytest.approx(-0.5)
    assert t4.trap_effect([True] * 20, [False] * 20) == 1.0


def test_the_resample_matrix_is_a_fresh_default_rng_20261130_each_time():
    matrix = t4.resample_matrix(100)
    expected = np.random.default_rng(20261130).choice(100, size=(10_000, 100), replace=True)
    assert matrix.shape == (10_000, 100)
    assert np.array_equal(matrix, expected)
    assert np.array_equal(t4.resample_matrix(100), matrix)


def test_a_pairs_ceiling_is_the_mean_with_a_percentile_bootstrap_ci():
    differences = np.random.default_rng(1).normal(0.02, 0.1, size=100)
    pair = t4.pair_ceiling(differences, t4.resample_matrix(100))
    assert pair["mean"] == pytest.approx(differences.mean(), abs=1e-15)
    assert pair["ci"] == pytest.approx(bootstrap_by_definition(differences), abs=1e-12)
    assert pair["excludes_zero"] == (pair["ci"][0] > 0 or pair["ci"][1] < 0)


def test_a_ci_excludes_zero_only_strictly():
    matrix = t4.resample_matrix(100)
    assert t4.pair_ceiling(np.zeros(100), matrix) == {"mean": 0.0, "ci": [0.0, 0.0], "excludes_zero": False}
    assert t4.pair_ceiling(np.full(100, 0.05), matrix)["excludes_zero"] is True
    assert t4.pair_ceiling(np.full(100, -0.05), matrix)["excludes_zero"] is True
    one_world = t4.pair_ceiling(np.array([0.0] * 99 + [1.0]), matrix)
    assert one_world["ci"][0] == 0.0 < one_world["ci"][1]
    assert one_world["excludes_zero"] is False


def test_the_five_pairs_are_stage_as_and_each_difference_is_first_minus_second():
    assert [tuple(p) for p in t4.PAIRS] == STAGE_A_PAIRS
    effects = {"fixed": np.zeros(100), "random": np.full(100, -0.1), "adaptive_name": np.full(100, 0.1),
               "adaptive_content": np.full(100, 0.05)}
    means = {(p["a"], p["b"]): p["mean"] for p in t4.trap_ceiling(effects)}
    assert means == pytest.approx({
        ("adaptive_name", "fixed"): 0.1, ("adaptive_name", "random"): 0.2, ("adaptive_content", "fixed"): 0.05,
        ("adaptive_content", "random"): 0.15, ("adaptive_name", "adaptive_content"): 0.05,
    })


def test_every_pair_in_a_trap_shares_one_matrix_and_each_trap_draws_it_fresh():
    rng = np.random.default_rng(2)
    base = rng.normal(0, 0.1, size=100)
    shift = rng.normal(0, 0.1, size=100)
    # adaptive_name - fixed and adaptive_content - random are the same vector.
    effects = {"fixed": shift, "adaptive_name": shift + base, "random": -shift, "adaptive_content": -shift + base}
    first = t4.trap_ceiling(effects)
    by_pair = {(p["a"], p["b"]): p for p in first}
    assert by_pair[("adaptive_name", "fixed")]["ci"] == by_pair[("adaptive_content", "random")]["ci"]
    assert by_pair[("adaptive_name", "fixed")]["ci"] == pytest.approx(bootstrap_by_definition(base), abs=1e-12)
    assert t4.trap_ceiling(effects) == first  # the next trap starts from the same fresh generator


def ceiling_with(excluding):
    return [{"a": a, "b": b, "mean": 0.0, "ci": [0.0, 0.0], "excludes_zero": (a, b) in excluding}
            for a, b in STAGE_A_PAIRS]


def test_stage_b_takes_a_ci_trap_on_any_excluding_pair_and_the_summary_trap_by_the_reads_clause():
    ceiling = {
        1: ceiling_with({("adaptive_name", "adaptive_content")}),
        2: ceiling_with(set()),
        3: ceiling_with(set()),
        4: ceiling_with({("adaptive_content", "fixed"), ("adaptive_name", "random")}),
    }
    chosen = t4.choose_stage_b(ceiling)
    assert {trap: c["goes_to_b"] for trap, c in chosen.items()} == {1: True, 2: False, 3: True, 4: True}
    assert {trap: c["rule"] for trap, c in chosen.items()} == {1: "ci", 2: "ci", 3: "reads clause", 4: "ci"}
    assert chosen[4]["pairs_excluding_zero"] == ["adaptive_name - random", "adaptive_content - fixed"]
    everything = {trap: ceiling_with(set(STAGE_A_PAIRS)) for trap in (1, 2, 3, 4)}
    assert t4.choose_stage_b(everything)[3]["rule"] == "reads clause"


def test_naming_is_named_on_exposure_runs_not_exposed_and_false_names_in_twins():
    summary = t4.naming_summary([True, False, None, True, None, None], [True, False, False, False])
    assert summary == {
        "trapped_runs": 6, "exposed": 3, "named": 2, "named_on_exposure": 2 / 3, "not_exposed": 3,
        "twin_runs": 4, "false_names": 1, "false_name_rate": 0.25,
    }
    assert t4.naming_summary([None, None], [])["named_on_exposure"] is None


def test_activity_splits_turns_and_distinct_contents_by_recovery():
    runs = [
        {"recovered": True, "turns_used": 2, "distinct_contents": 1},
        {"recovered": True, "turns_used": 4, "distinct_contents": 3},
        {"recovered": False, "turns_used": 9, "distinct_contents": 7},
    ]
    assert t4.activity_summary(runs) == {
        "recovered": {"runs": 2, "mean_turns_used": 3.0, "mean_distinct_contents": 2.0},
        "not_recovered": {"runs": 1, "mean_turns_used": 9.0, "mean_distinct_contents": 7.0},
    }


# --------------------------------------------------------------- provenance

GIVEN = {"worlds_code_hash": "w" * 64, "policies_code_hash": "p" * 64, "worlds_fingerprint": "f" * 64}


@pytest.mark.parametrize("missing", sorted(GIVEN))
@pytest.mark.parametrize("value", [None, "", "  \n"])
def test_stage_a_refuses_without_each_hash_and_the_fingerprint_before_importing(missing, value):
    with pytest.raises(t4.Refused, match=missing):
        t4.run_stage_a(worlds_module="no_such_t4_worlds", policies_module="no_such_t4_policies",
                       **{**GIVEN, missing: value})


def cli_args(out, **overrides):
    args = {"--worlds-module": "no_such_t4_worlds", "--policies-module": "no_such_t4_policies",
            "--worlds-code-hash": "w", "--policies-code-hash": "p", "--fingerprint": "f", "--out": str(out)}
    args.update(overrides)
    return [part for key, value in args.items() if value is not None for part in (key, value)]


def test_the_cli_refuses_an_empty_fingerprint_and_a_missing_one(tmp_path, capsys):
    out = tmp_path / "result.json"
    assert t4.main(cli_args(out, **{"--fingerprint": ""})) == 2
    assert "worlds_fingerprint" in capsys.readouterr().err
    assert not out.exists()
    with pytest.raises(SystemExit) as exited:
        t4.main(cli_args(out, **{"--fingerprint": None}))
    assert exited.value.code == 2 and not out.exists()


def test_a_half_missing_an_export_is_refused(monkeypatch):
    worlds = types.ModuleType("fake_t4_partial_worlds")
    worlds.worlds = lambda: iter(())
    worlds.named = lambda w, r, f: None
    policies = types.ModuleType("fake_t4_partial_policies")
    for name in ("fixed", "random", "adaptive_name"):
        setattr(policies, name, lambda r, o, s: (0, []))
    monkeypatch.setitem(sys.modules, worlds.__name__, worlds)
    monkeypatch.setitem(sys.modules, policies.__name__, policies)
    with pytest.raises(t4.ContractError, match="false_named"):
        t4.load_halves(worlds.__name__, policies.__name__)
    worlds.false_named = lambda w, r, f: False
    with pytest.raises(t4.ContractError, match="adaptive_content"):
        t4.load_halves(worlds.__name__, policies.__name__)


# --------------------------------------------- a planted run of all 800 worlds
#
# Planted tables, no model. World j of trap t has 80 approaches at L0, one per
# policy and seed, so the table decides each run: seeds below a cut recover at
# turn seed % 3 + 1 and the rest never do (budget 3). A twin's cut is
# 10 + j % 7; a trapped world's cut is lower by the trap's loss for that policy.
# D, k and w repeat across 50 worlds of a trap, and the twins come out of
# worlds() in another order, so only the seed joins a trapped world to its twin.

PLANT_BUDGET = 3


def plant_seed(trap, j):
    return 1000 * trap + 7 * j + 3


def twin_cut(j):
    return 10 + j % 7


def plant_loss(trap, j, policy):
    if trap == 1:
        return {"fixed": 5, "random": 5, "adaptive_name": j % 3, "adaptive_content": 0}[policy]
    if trap in (2, 3):
        return 2
    return {"fixed": j % 4, "random": j % 4, "adaptive_name": j % 4 + j % 2, "adaptive_content": 3 * j % 4}[policy]


def plant_turn(trap, j, form, policy, seed):
    cut = twin_cut(j) - (plant_loss(trap, j, policy) if form == "trapped" else 0)
    return seed % 3 + 1 if seed < cut else None


class PlantedWorld:
    def __init__(self, trap, j, form):
        self.trap, self.j, self.form = trap, j, form
        self.seed = plant_seed(trap, j)
        self.budget = PLANT_BUDGET

    @staticmethod
    def content(policy, seed, n):
        # random tries a new content every turn; the others repeat one.
        return f"c:{policy}:{seed}:{n}" if policy == "random" else f"c:{policy}:{seed}"

    def options(self, state):
        if state == "L0":
            return [{"name": f"{p}:{s}", "content": self.content(p, s, 0)} for p in CONTRACT_POLICIES
                    for s in CONTRACT_SEEDS]
        _, policy, seed, n = state.split(":")
        return [{"name": f"{policy}:{seed}", "content": self.content(policy, seed, int(n))}]

    def step(self, state, approach):
        policy, seed = approach["name"].split(":")
        n = 0 if state == "L0" else int(state.split(":")[3])
        nxt = f"S:{policy}:{seed}:{n + 1}"
        return nxt, entry_for(nxt, approach["name"], approach["content"], "pass" if self.recovered(nxt) else "fail")

    def recovered(self, state):
        if state == "L0":
            return False
        _, policy, seed, n = state.split(":")
        turn = plant_turn(self.trap, self.j, self.form, policy, int(seed))
        return turn is not None and int(n) >= turn


def all_four(record):
    state = record[-1]["state"] if record else "L0"
    return [{"cycle": state}, {"repeat": "c"}, {"contradiction": len(record)}, {"premise": len(record)}]


def planted_policy(name):
    """adaptive_name raises all four flags at the first call, adaptive_content
    at the call just after turn 1, random raises cycle at the first call on
    every fourth seed, and fixed raises nothing."""

    def policy(record, options, seed):
        index = [o["name"] for o in options].index(f"{name}:{seed}")
        made_with = len(record)
        if name == "adaptive_name":
            flags = all_four(record) if made_with == 0 else []
        elif name == "adaptive_content":
            flags = all_four(record) if made_with == 1 else []
        elif name == "random":
            flags = [{"cycle": "L0"}] if made_with == 0 and seed % 4 == 0 else []
        else:
            flags = []
        return index, flags

    return policy


def planted_halves():
    worlds = types.ModuleType("fake_t4_planted_worlds")
    policies = types.ModuleType("fake_t4_planted_policies")

    def item(trap, j, form):
        return {"world": PlantedWorld(trap, j, form), "trap": trap, "D": j % 2, "k": 3, "w": 1, "form": form}

    def all_worlds():
        for trap in (1, 2, 3, 4):
            for j in range(100):
                yield item(trap, j, "trapped")
        for trap in (4, 3, 2, 1):
            for i in range(100):
                yield item(trap, 37 * i % 100, "twin")

    def named(world, record, flags_per_call):
        # The planted rule names the call just after turn 1, which exists only
        # when a second turn was taken.
        if world.form != "trapped" or len(record) < 2:
            return None
        return any(CONTRACT_TRAP_FLAG[world.trap] in flag for flag in flags_per_call[1])

    def false_named(world, record, flags_per_call):
        flag = CONTRACT_TRAP_FLAG[world.trap]
        return world.form == "twin" and any(flag in raised for call in flags_per_call for raised in call)

    worlds.worlds, worlds.named, worlds.false_named = all_worlds, named, false_named
    for name in CONTRACT_POLICIES:
        setattr(policies, name, planted_policy(name))
    return worlds, policies


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    worlds, policies = planted_halves()
    sys.modules[worlds.__name__] = worlds
    sys.modules[policies.__name__] = policies
    out = tmp_path_factory.mktemp("t4") / "stage-a.json"
    try:
        code = t4.main(cli_args(out, **{
            "--worlds-module": worlds.__name__, "--policies-module": policies.__name__,
            "--worlds-code-hash": "wh", "--policies-code-hash": "ph", "--fingerprint": "fp",
        }))
    finally:
        del sys.modules[worlds.__name__], sys.modules[policies.__name__]
    assert code == 0
    return json.loads(out.read_text())


def recovered_seeds(trap, j, form, policy):
    return sum(plant_turn(trap, j, form, policy, s) is not None for s in CONTRACT_SEEDS)


def expected_effects(trap):
    return {
        p: np.array([(recovered_seeds(trap, j, "trapped", p) - recovered_seeds(trap, j, "twin", p)) / 20
                     for j in range(100)])
        for p in CONTRACT_POLICIES
    }


def turns_taken(trap, j, form, policy, seed):
    turn = plant_turn(trap, j, form, policy, seed)
    return PLANT_BUDGET if turn is None else turn


def test_planted_every_world_runs_every_policy_on_every_seed(planted):
    assert planted["scorer_test"] == {
        "worlds": 800, "policies": 4, "seeds": 20, "runs": 64_000, "named_calls": 64_000,
        "false_named_calls": 32_000, "recovery_checks": planted["scorer_test"]["recovery_checks"],
        "policy_calls": planted["scorer_test"]["recovery_checks"],
    }
    expected_turns = sum(turns_taken(t, j, f, p, s) for t in (1, 2, 3, 4) for j in range(100)
                         for f in ("trapped", "twin") for p in CONTRACT_POLICIES for s in CONTRACT_SEEDS)
    assert planted["scorer_test"]["recovery_checks"] == expected_turns
    assert len(planted["runs"]["rows"]) == 64_000


def test_planted_records_what_it_was_given(planted):
    assert {k: planted["provenance"][k] for k in GIVEN} == {
        "worlds_code_hash": "wh", "policies_code_hash": "ph", "worlds_fingerprint": "fp"}
    assert planted["provenance"]["worlds_module"] == "fake_t4_planted_worlds"
    assert (planted["stage"], planted["label"]) == ("A", "argued, checked")


def test_planted_worlds_are_listed_in_trapped_order_with_their_seeds(planted):
    for trap in (1, 2, 3, 4):
        assert planted["worlds"][str(trap)] == [
            {"index": j, "D": j % 2, "k": 3, "w": 1, "seed": plant_seed(trap, j)} for j in range(100)]


def test_planted_trap_effects_are_per_world_over_its_20_paired_seeds(planted):
    for trap in (1, 2, 3, 4):
        expected = expected_effects(trap)
        for policy in CONTRACT_POLICIES:
            assert planted["ceiling"][str(trap)]["trap_effects"][policy] == pytest.approx(
                list(expected[policy]), abs=1e-12)
            assert planted["ceiling"][str(trap)]["mean_trap_effect"][policy] == pytest.approx(
                expected[policy].mean(), abs=1e-12)
    assert planted["ceiling"]["1"]["trap_effects"]["fixed"] == pytest.approx([-0.25] * 100, abs=1e-12)


def test_planted_pairs_are_the_mean_difference_with_the_bootstrap_ci(planted):
    for trap in (1, 2, 3, 4):
        expected = expected_effects(trap)
        pairs = planted["ceiling"][str(trap)]["pairs"]
        assert [(p["a"], p["b"]) for p in pairs] == STAGE_A_PAIRS
        for pair in pairs:
            differences = expected[pair["a"]] - expected[pair["b"]]
            low, high = bootstrap_by_definition(differences)
            assert pair["mean"] == pytest.approx(differences.mean(), abs=1e-12)
            assert pair["ci"] == pytest.approx([low, high], abs=1e-12)
            assert pair["excludes_zero"] is (low > 0 or high < 0)


def expected_excluding(trap):
    effects = expected_effects(trap)
    excluding = []
    for a, b in STAGE_A_PAIRS:
        low, high = bootstrap_by_definition(effects[a] - effects[b])
        if low > 0 or high < 0:
            excluding.append(f"{a} - {b}")
    return excluding


def test_planted_stage_b_traps(planted):
    chosen = planted["stage_b"]
    for trap in (1, 2, 4):
        excluding = expected_excluding(trap)
        assert chosen[str(trap)] == {"rule": "ci", "goes_to_b": bool(excluding), "pairs_excluding_zero": excluding}
    # The summary trap's CIs all hold zero, and it goes by the reads clause anyway.
    assert expected_excluding(3) == []
    assert chosen["3"] == {"rule": "reads clause", "goes_to_b": True, "pairs_excluding_zero": []}
    # As planted: trap 1's and trap 4's unequal losses exclude zero, trap 2's equal losses don't.
    assert {t: chosen[t]["goes_to_b"] for t in chosen} == {"1": True, "2": False, "3": True, "4": True}
    assert "adaptive_content - fixed" in chosen["1"]["pairs_excluding_zero"]
    assert {"adaptive_name - fixed", "adaptive_name - random"} <= set(chosen["4"]["pairs_excluding_zero"])


def test_planted_naming_beside_the_ceiling(planted):
    for trap in (1, 2, 3, 4):
        for policy in CONTRACT_POLICIES:
            turns = [turns_taken(trap, j, "trapped", policy, s) for j in range(100) for s in CONTRACT_SEEDS]
            exposed = sum(t >= 2 for t in turns)
            named = exposed if policy == "adaptive_content" else 0
            twin_turns = [(turns_taken(trap, j, "twin", policy, s), s) for j in range(100) for s in CONTRACT_SEEDS]
            if policy == "adaptive_name":
                false_names = 2000
            elif policy == "adaptive_content":
                false_names = sum(t >= 2 for t, _ in twin_turns)
            elif policy == "random":
                false_names = 500 if trap == 1 else 0
            else:
                false_names = 0
            assert planted["naming"][str(trap)][policy] == {
                "trapped_runs": 2000, "exposed": exposed, "named": named,
                "named_on_exposure": named / exposed, "not_exposed": 2000 - exposed,
                "twin_runs": 2000, "false_names": false_names, "false_name_rate": false_names / 2000,
                "false_named_disagrees_with_flag_map": 0,
            }


def test_planted_recovery_and_activity_beside_the_scores(planted):
    for trap in (1, 2, 3, 4):
        for form in ("trapped", "twin"):
            for policy in CONTRACT_POLICIES:
                turns = [plant_turn(trap, j, form, policy, s) for j in range(100) for s in CONTRACT_SEEDS]
                won = [t for t in turns if t is not None]
                lost = len(turns) - len(won)
                distinct = (lambda t: t) if policy == "random" else (lambda t: 1)
                assert planted["recovery"][str(trap)][form][policy] == pytest.approx({
                    "runs": 2000, "recovered": len(won), "rate": len(won) / 2000,
                    "mean_turns_to_recovery": sum(won) / len(won)})
                activity = planted["activity"][str(trap)][form][policy]
                assert activity["recovered"] == pytest.approx({
                    "runs": len(won), "mean_turns_used": sum(won) / len(won),
                    "mean_distinct_contents": sum(map(distinct, won)) / len(won)})
                assert lost > 0
                assert activity["not_recovered"] == pytest.approx({
                    "runs": lost, "mean_turns_used": 3.0, "mean_distinct_contents": distinct(3)})


def test_planted_run_rows_log_every_calls_flags(planted):
    columns = planted["runs"]["columns"]
    rows = {(r[0], r[1], r[2], r[3], r[4]): dict(zip(columns, r)) for r in planted["runs"]["rows"]}
    assert len(rows) == 64_000
    for trap, j, form, policy, seed in [(1, 5, "trapped", "adaptive_content", 4), (4, 61, "twin", "random", 8),
                                        (2, 0, "trapped", "adaptive_name", 0), (3, 99, "twin", "fixed", 19)]:
        row = rows[(trap, j, form, policy, seed)]
        turn = plant_turn(trap, j, form, policy, seed)
        used = turns_taken(trap, j, form, policy, seed)
        assert (row["recovered"], row["turns_to_recovery"], row["turns_used"]) == (turn is not None, turn, used)
        assert len(row["flags_per_call"]) == used
        flags = planted_policy(policy)
        state = "L0"
        for made_with, logged in enumerate(row["flags_per_call"]):
            record = [{"state": f"S:{policy}:{seed}:{n + 1}"} for n in range(made_with)]
            options = PlantedWorld(trap, j, form).options(record[-1]["state"] if record else state)
            assert logged == flags(record, options, seed)[1]
        if form == "trapped":
            assert row["named"] is ((policy == "adaptive_content") if used >= 2 else None)
            assert row["false_named"] is None
        else:
            assert row["named"] is None
            raised = any(CONTRACT_TRAP_FLAG[trap] in f for call in row["flags_per_call"] for f in call)
            assert row["false_named"] is raised
