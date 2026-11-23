"""North-star test 4, stage B: the harness, pinned to the approved spec with a stub call_turn.

No test here runs a model, the systemd scope, bubblewrap or `claude`. The stub `call_turn` is a Python function that
returns canned TurnResults: JSON replies, malformed replies, timeouts and faults. Expected values come from the
spec's text and the halves' exports (`open_patches`, `prompt`), computed here apart from the harness.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from experiments.northstar import test4b_arms as A
from experiments.northstar import test4b_harness as H
from experiments.northstar import test4b_worlds as W

ALL = W.worlds()
BY_KEY = {(w["trap"], w["w"], w["form"]): w for w in ALL}


def world(trap: int, w: int = 0, form: str = "trapped") -> dict:
    return BY_KEY[(trap, w, form)]


def reply(choice, summary: str = "Tried it.", flags=()) -> H.TurnResult:
    return H.TurnResult.reply(json.dumps({"choice": choice, "summary": summary, "flags": list(flags)}))


class Script:
    """A stub call_turn: returns the scripted outcomes in order, and keeps every prompt it was given."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> H.TurnResult:
        self.prompts.append(prompt)
        if not self.outcomes:
            raise AssertionError("the harness called past the script")
        return self.outcomes.pop(0)


def failing(wd: dict, *avoid: int) -> int:
    return next(x for x in range(5) if x != wd["passing"] and x not in avoid)


def expected_prompt(arm: str, wd: dict, record: list, i: int, seed: int) -> str:
    """The prompt the spec says a turn gets, computed here from the halves' exports."""
    patches = W.open_patches(wd, record, i)
    given = [{"description": p["name"], "diff": p["diff"]} for p in patches]
    entries = [
        {"turn": e["turn"], "description": e["name"], "diff": e["diff"],
         "verdict": e["verdict"], "summary": e["summary"]}
        for e in record
    ]
    keys = [e["content"] for e in record] + [p["content"] for p in patches] if arm == "R2" else None
    return A.prompt(arm, wd["task"], given, entries, keys=keys, seed=seed)


def patched_by_hand(base: str, diff: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "target.py").write_text(base, newline="")
        subprocess.run(["patch", "-p1", "-s"], input=diff, cwd=tmp, text=True, check=True)
        return Path(tmp, "target.py").read_text()


def spec_key(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


# ------------------------------------------------------------------ prompts come from the arms


@pytest.mark.parametrize("arm", ["R0", "R1", "R2"])
def test_every_prompt_is_the_arms_prompt_on_the_record_and_open_patches(arm):
    wd = world(5)  # the unchecked entry: a null verdict and a null summary in the record
    f = failing(wd)
    script = Script([reply(f, "Tried one."), reply(wd["passing"], "Tried the other.")])
    result = H.run(wd, arm, 2, call_turn=script, pause=lambda s: None)
    n = len(wd["planted"])
    assert len(script.prompts) == 2
    assert script.prompts[0] == expected_prompt(arm, wd, list(wd["planted"]), 1, seed=2)
    assert script.prompts[1] == expected_prompt(arm, wd, result["record"][: n + 1], 2, seed=2)
    assert result["seed"] == 2


def test_r2_gets_one_key_per_entry_null_verdict_included_then_one_per_patch():
    wd = world(5)
    patches = W.open_patches(wd, list(wd["planted"]), 1)
    keys = H.r2_keys(wd["planted"], patches)
    assert len(keys) == len(wd["planted"]) + 5
    assert wd["planted"][-1]["verdict"] is None and keys[len(wd["planted"]) - 1] == wd["planted"][-1]["content"]
    assert keys[-5:] == [p["content"] for p in patches]


def test_the_advice_seed_is_the_repeat_and_a_given_seed_overrides_it():
    wd = world(5)
    for repeat in (0, 1, 2):
        script = Script([reply(wd["passing"])])
        result = H.run(wd, "R2", repeat, call_turn=script)
        assert result["seed"] == repeat
        assert script.prompts[0] == expected_prompt("R2", wd, list(wd["planted"]), 1, seed=repeat)
    script = Script([reply(wd["passing"])])
    assert H.run(wd, "R2", 0, seed=7, call_turn=script)["seed"] == 7
    assert script.prompts[0] == expected_prompt("R2", wd, list(wd["planted"]), 1, seed=7)


# ------------------------------------------------------------------ the patch is applied and the verdict taken


def test_the_chosen_patch_is_applied_on_that_turns_base_and_its_verdict_recorded():
    wd = world(4)  # the base moves before every run turn
    n = len(wd["planted"])
    f = failing(wd)
    script = Script([reply(f, "First try."), reply(wd["passing"], "Second try.")])
    result = H.run(wd, "R1", 0, call_turn=script)
    first, second = result["record"][n], result["record"][n + 1]
    offered = W.open_patches(wd, list(wd["planted"]), 1)[f]
    assert first == {
        "turn": n + 1,
        "state": "S2",
        "index": f,
        "name": offered["name"],
        "diff": offered["diff"],
        "content": offered["content"],
        "verdict": "fail",
        "summary": "First try.",
        "says": None,
        "observation": None,
    }
    # The content is the patched file's key on run turn 1's base (bases[1]), not on the planted entries' base.
    assert spec_key(patched_by_hand(wd["bases"][1], first["diff"])) == first["content"]
    assert first["content"] != wd["patches"][0][f]["content"]
    assert second["verdict"] == "pass" and second["state"] == "G" and second["turn"] == n + 2
    assert second["summary"] == "Second try."
    assert result["recovered"] is True and result["recovered_at"] == 2
    assert len(script.prompts) == 2  # the run stops at its pass


def test_the_verdict_is_the_frozen_tests_exit_code_not_the_worlds_passing_field():
    wd = dict(world(2))
    digest = wd["test"].split('DIGEST = "')[1].split('"')[0]
    wd["test"] = wd["test"].replace(digest, "0" * 64)  # now no patch can pass
    script = Script([reply(wd["passing"])] * 7)
    result = H.run(wd, "R0", 0, call_turn=script)
    assert [e["verdict"] for e in result["record"][len(wd["planted"]) :]] == ["fail"] * 7
    assert result["recovered"] is False and result["turns"] == 7


def test_apply_and_test_runs_patch_then_pytest_and_refuses_a_wrong_key_or_a_broken_test():
    wd = world(1)
    patches = W.open_patches(wd, list(wd["planted"]), 1)
    base = H.base_for(wd, 1)
    p, f = wd["passing"], failing(wd)
    patched, verdict = H.apply_and_test(base, patches[p]["diff"], wd["test"], expect=patches[p]["content"])
    assert verdict == "pass" and patched == patched_by_hand(base, patches[p]["diff"])
    assert H.apply_and_test(base, patches[f]["diff"], wd["test"], expect=patches[f]["content"])[1] == "fail"
    with pytest.raises(H.HarnessError, match="key"):
        H.apply_and_test(base, patches[p]["diff"], wd["test"], expect="0" * 64)
    with pytest.raises(H.HarnessError, match="exited"):
        H.apply_and_test(base, patches[p]["diff"], "def test_x(:\n")
    with pytest.raises(H.HarnessError, match="patch -p1"):
        H.apply_and_test("nothing like the base\n", patches[p]["diff"], wd["test"])


def test_the_harness_key_is_the_spec_normalization():
    assert H.normalize("a  \r\nb\t\n\n\n") == "a\nb\n"
    assert H.content_key("x = 1 \r\n\n") == hashlib.sha256(b"x = 1\n").hexdigest()


# ------------------------------------------------------------------ stalls write no entry, and i counts them


def test_stalls_write_no_entry_raise_no_flags_and_still_move_i():
    wd = world(4)
    n = len(wd["planted"])
    f = failing(wd)
    script = Script(
        [
            H.TurnResult.stall("timeout"),
            H.TurnResult.reply('{"choice": 1, "summary": "no flags key"}'),
            reply(f, "Third call.", flags=[{"repeat": 0}]),
            reply(wd["passing"]),
        ]
    )
    result = H.run(wd, "R1", 0, call_turn=script)
    assert result["stalls"] == {"timeout": 1, "malformed": 1}
    assert result["stall_turns"] == [1, 2]
    record = result["record"]
    assert len(record) == n + 2
    entry = record[n]
    assert entry["turn"] == n + 3  # a gap: run turns 1 and 2 stalled
    assert entry["state"] == "S4"
    offered = W.open_patches(wd, list(wd["planted"]), 3)
    assert entry["content"] == offered[f]["content"]  # the base offered after two stalls is run turn 3's
    assert script.prompts[2] == expected_prompt("R1", wd, list(wd["planted"]), 3, seed=0)
    assert script.prompts[0] != script.prompts[2]
    # One read call per record length; the stalls left nothing.
    assert result["flags_per_call"][:n] == [[]] * n
    assert result["flags_per_call"][n] == [{"repeat": offered[0]["content"]}]
    assert len(result["flags_per_call"]) == n + 2
    assert result["turns"] == 4 and result["recovered_at"] == 4 and result["calls"] == 4


def test_a_run_of_stalls_spends_the_budget_and_writes_nothing():
    wd = world(2)
    script = Script([H.TurnResult.stall("timeout"), H.TurnResult.reply("I pick 3")] * 4)
    result = H.run(wd, "R1", 0, call_turn=script)
    assert result["record"] == list(wd["planted"])
    assert result["turns"] == 7 and result["entries"] == 0 and len(script.prompts) == 7
    assert result["recovered"] is False
    assert result["named"] is None and result["raised"] is None  # no reply was read, so no rule call


def test_firing_turns_count_stalls():
    wd = world(1)
    returner = wd["planted"][0]["index"]
    no_stall = H.run(wd, "R1", 0, call_turn=Script([reply(returner), reply(wd["passing"])]))
    assert no_stall["firing"] == [1]
    stalled = H.run(
        wd, "R1", 0, call_turn=Script([H.TurnResult.stall("timeout"), reply(returner), reply(wd["passing"])])
    )
    assert stalled["firing"] == [2]


def test_the_first_run_call_is_the_first_whose_reply_was_read():
    wd = world(2)
    planted_turn = wd["planted"][0]["turn"]
    script = Script([H.TurnResult.reply("{}"), reply(wd["passing"], flags=[{"contradiction": planted_turn}])])
    result = H.run(wd, "R1", 0, call_turn=script)
    assert result["named"] is True


# ------------------------------------------------------------------ faults retry, then void, then rerun


def test_a_fault_is_retried_once_after_the_pause_and_doesnt_move_i():
    wd = world(2)
    pauses = []
    script = Script([H.TurnResult.fault("result is_error"), reply(wd["passing"])])
    result = H.run(wd, "R0", 0, call_turn=script, pause=pauses.append)
    assert pauses == [60]
    assert result["faults"] == 1 and result["reruns"] == 0 and result["calls"] == 2
    assert result["turns"] == 1 and result["recovered_at"] == 1
    assert result["record"][-1]["turn"] == len(wd["planted"]) + 1
    assert script.prompts[0] == script.prompts[1]  # the same turn, retried


def test_two_faults_in_a_row_void_the_run_which_reruns_from_its_start():
    wd = world(1)
    n = len(wd["planted"])
    f = failing(wd, wd["planted"][0]["index"])
    pauses = []
    script = Script(
        [
            reply(f),  # attempt 1, turn 1
            H.TurnResult.fault("exited with no result"),  # attempt 1, turn 2
            H.TurnResult.fault("exited with no result"),  # its retry: void
            reply(wd["passing"]),  # attempt 2, turn 1
        ]
    )
    result = H.run(wd, "R1", 1, call_turn=script, pause=pauses.append)
    assert result["reruns"] == 1 and result["faults"] == 2 and result["calls"] == 4
    assert pauses == [60]
    assert result["voided"][0]["void_at"] == 2
    assert script.prompts[3] == script.prompts[0]  # the same world, form, arm, repeat and seed, from the start
    assert len(result["record"]) == n + 1 and result["record"][n]["index"] == wd["passing"]
    assert result["recovered_at"] == 1 and result["seed"] == 1


def test_a_stall_on_the_retry_is_a_stall():
    wd = world(2)
    script = Script([H.TurnResult.fault("result is_error"), H.TurnResult.stall("timeout"), reply(wd["passing"])])
    result = H.run(wd, "R0", 0, call_turn=script, pause=lambda s: None)
    assert result["faults"] == 1 and result["stalls"] == {"timeout": 1} and result["recovered_at"] == 2


def test_a_run_that_keeps_voiding_stops_the_series_instead_of_being_dropped():
    wd = world(3)
    pauses = []
    calls = []

    def always_fault(prompt):
        calls.append(prompt)
        return H.TurnResult.fault("result is_error")

    with pytest.raises(H.MachineDown):
        H.run(wd, "R2", 0, call_turn=always_fault, pause=pauses.append, max_reruns=2)
    assert len(calls) == 6 and pauses == [60, 60, 60]


# ------------------------------------------------------------------ the init check, and the stream


def stream(*events) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)


INIT_OK = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "model": "claude-sonnet-5-5"}
RETRY = {"type": "system", "subtype": "api_retry", "attempt": 1}


def result_event(text: str, is_error: bool = False) -> dict:
    return {
        "type": "result",
        "subtype": "error_during_execution" if is_error else "success",
        "is_error": is_error,
        "result": text,
        "usage": {"input_tokens": 1800, "output_tokens": 90},
        "total_cost_usd": 0.01,
    }


def test_the_init_check_refuses_tools_and_mcp_servers():
    good = result_event('{"choice": 0, "summary": "s", "flags": []}')
    ok = H.classify(stream(INIT_OK, good), killed=False, seconds=12.5)
    assert ok.kind == "reply" and ok.text == good["result"]
    assert ok.usage["input_tokens"] == 1800 and ok.usage["total_cost_usd"] == 0.01 and ok.seconds == 12.5
    with_tools = dict(INIT_OK, tools=["Bash", "Read"])
    assert H.classify(stream(with_tools, good), killed=False).kind == "fault"
    with_mcp = dict(INIT_OK, mcp_servers=[{"name": "station", "status": "connected"}])
    assert H.classify(stream(with_mcp, good), killed=False).kind == "fault"
    no_lists = {"type": "system", "subtype": "init"}
    assert H.classify(stream(no_lists, good), killed=False).kind == "fault"
    assert H.classify(stream(good), killed=False).kind == "fault"  # no init event, so no check was made


def test_the_stream_rules_for_stalls_and_faults():
    good = result_event('{"choice": 0, "summary": "s", "flags": []}')
    assert H.classify(stream(INIT_OK, result_event("Not signed in", True)), killed=False).kind == "fault"
    assert H.classify(stream(INIT_OK, RETRY), killed=True).kind == "fault"
    timeout = H.classify(stream(INIT_OK), killed=True)
    assert timeout.kind == "stall" and timeout.reason == "timeout"
    assert H.classify(stream(INIT_OK), killed=False).kind == "fault"  # exited on its own with no result
    assert H.classify("", killed=False).kind == "fault"
    assert H.classify("not json\n" + stream(INIT_OK, good), killed=False).kind == "reply"


def test_a_call_whose_init_lists_tools_never_reaches_the_record():
    wd = world(2)
    f = failing(wd)
    passing_text = json.dumps({"choice": wd["passing"], "summary": "s", "flags": []})
    failing_text = json.dumps({"choice": f, "summary": "s", "flags": []})
    tool_call = H.classify(stream(dict(INIT_OK, tools=["Bash"]), result_event(passing_text)), killed=False)
    clean = H.classify(stream(INIT_OK, result_event(failing_text)), killed=False)
    script = Script([tool_call, clean, reply(wd["passing"])])
    result = H.run(wd, "R1", 0, call_turn=script, pause=lambda s: None)
    n = len(wd["planted"])
    assert result["faults"] == 1 and result["record"][n]["index"] == f  # the tool call's reply was refused
    always = Script([tool_call] * 2)
    with pytest.raises(H.MachineDown):
        H.run(wd, "R1", 0, call_turn=always, pause=lambda s: None, max_reruns=0)


# ------------------------------------------------------------------ naming maps repeat numbers to keys


@pytest.mark.parametrize("value", ["int", "str", "padded"])
def test_a_repeat_number_becomes_that_patchs_key_at_that_call(value):
    wd = world(1)
    n = len(wd["planted"])
    returner = wd["planted"][0]["index"]
    given = {"int": returner, "str": str(returner), "padded": f" {returner} "}[value]
    script = Script([reply(failing(wd, returner), flags=[{"repeat": given}]), reply(wd["passing"])])
    result = H.run(wd, "R1", 0, call_turn=script)
    key = W.open_patches(wd, list(wd["planted"]), 1)[returner]["content"]
    assert result["flags_per_call"][n] == [{"repeat": key}]
    assert result["raw_flags_per_call"][n] == [{"repeat": given}]
    assert result["named"] is True and result["raised"] is True


@pytest.mark.parametrize("given", ["patch 1", 7, True, -1, 1.0, "the zinc patch"])
def test_a_repeat_value_that_isnt_a_patch_number_stays_as_written(given):
    wd = world(1)
    n = len(wd["planted"])
    text = json.dumps({"choice": wd["passing"], "summary": "s", "flags": [{"repeat": given}]})
    script = Script([H.TurnResult.reply(text), reply(wd["passing"])])
    result = H.run(wd, "R1", 0, call_turn=script)
    try:
        A.read_reply(text, 5)
    except A.Malformed:
        # The arms refuse this value, so the reply is a stall and never reaches naming.
        assert result["stalls"] == {"malformed": 1} and result["flags_per_call"][n] == []
        return
    assert result["flags_per_call"][n] == [{"repeat": given}]
    assert result["named"] is False and result["raised"] is True


def test_trap_4_logs_the_key_at_that_call_and_scores_the_key_as_recorded():
    wd = world(4)
    n = len(wd["planted"])
    planted_idea = wd["planted"][0]["index"]
    script = Script([reply(wd["passing"], flags=[{"repeat": planted_idea}])])
    result = H.run(wd, "R2", 0, call_turn=script)
    now = W.open_patches(wd, list(wd["planted"]), 1)[planted_idea]["content"]
    assert result["flags_per_call"][n] == [{"repeat": now}]  # logged: the key at that call
    assert now != wd["planted"][0]["content"]  # the key moved with the base
    assert result["scoring_flags_per_call"][n] == [{"repeat": wd["planted"][0]["content"]}]  # scored: as recorded
    assert wd["planted"][0]["content"] == wd["patches"][0][planted_idea]["content"]
    assert result["named"] is True


@pytest.mark.parametrize("arm", ["R1", "R2"])
def test_trap_4_is_named_after_a_stalled_first_turn(arm):
    """Review, required change 1: after a stall, the first read call's base is bases[2], whose key the rule doesn't
    take; the key as recorded (bases[0]) is what it scores."""
    wd = world(4)
    n = len(wd["planted"])
    planted_idea = wd["planted"][0]["index"]
    script = Script([H.TurnResult.stall("timeout"), reply(wd["passing"], flags=[{"repeat": planted_idea}])])
    result = H.run(wd, arm, 0, call_turn=script)
    at_call = W.open_patches(wd, list(wd["planted"]), 2)[planted_idea]["content"]
    assert result["stall_turns"] == [1]
    assert result["flags_per_call"][n] == [{"repeat": at_call}]
    assert result["scoring_flags_per_call"][n] == [{"repeat": wd["patches"][0][planted_idea]["content"]}]
    assert result["named"] is True and result["raised"] is True
    # The at-that-call key alone would have lost it, which is the change's reason.
    assert W.named(wd, result["record"], result["flags_per_call"]) is False


def test_trap_4_is_named_with_no_stall_too():
    wd = world(4)
    planted_idea = wd["planted"][1]["index"]  # the other planted idea, failed at turn 2
    result = H.run(wd, "R1", 0, call_turn=Script([reply(wd["passing"], flags=[{"repeat": str(planted_idea)}])]))
    assert result["stall_turns"] == [] and result["named"] is True


@pytest.mark.parametrize("stall_first", [False, True])
def test_trap_1_naming_is_unaffected_by_the_scoring_map(stall_first):
    wd = world(1)
    n = len(wd["planted"])
    returner = wd["planted"][0]["index"]
    outcomes = [H.TurnResult.stall("timeout")] if stall_first else []
    outcomes += [reply(wd["passing"], flags=[{"repeat": returner}])]
    result = H.run(wd, "R1", 0, call_turn=Script(outcomes))
    assert result["scoring_flags_per_call"] == result["flags_per_call"]  # one base: the two maps agree
    assert result["flags_per_call"][n] == [{"repeat": wd["planted"][0]["content"]}]
    assert result["named"] is True
    wrong = failing(wd, returner)
    result = H.run(wd, "R1", 0, call_turn=Script(outcomes[:-1] + [reply(wd["passing"], flags=[{"repeat": wrong}])]))
    assert result["named"] is False and result["raised"] is True


def test_a_twin_scores_false_names_and_trap_3_scores_raised():
    twin = world(1, form="twin")
    returner = twin["planted"][0]["index"]
    result = H.run(twin, "R1", 0, call_turn=Script([reply(twin["passing"], flags=[{"repeat": returner}])]))
    assert result["false_named"] is True and result["named"] is None
    cycle = world(3)
    result = H.run(cycle, "R1", 0, call_turn=Script([reply(cycle["passing"], flags=[{"cycle": "these loop"}])]))
    assert result["raised"] is True and result["named"] is False


def test_map_flags_only_touches_repeat():
    patches = [{"content": f"key{x}"} for x in range(5)]
    flags = [{"repeat": "2"}, {"contradiction": "1"}, {"premise": 5}, {"cycle": "3"}]
    assert H.map_flags(flags, patches) == [{"repeat": "key2"}, {"contradiction": "1"}, {"premise": 5}, {"cycle": "3"}]


def test_string_contradiction_and_premise_values_are_counted():
    two = world(2)
    five = world(5)
    runs = [
        H.run(two, "R1", 0, call_turn=Script([reply(two["passing"], flags=[{"contradiction": "1"}])])),
        H.run(two, "R2", 0, call_turn=Script([reply(two["passing"], flags=[{"contradiction": 1}])])),
        H.run(
            five, "R1", 0,
            call_turn=Script([reply(five["passing"], flags=[{"premise": "5"}, {"contradiction": "2"}])]),
        ),
    ]
    assert runs[0]["named"] is False and runs[1]["named"] is True  # the worlds take only an integer turn
    assert H.string_turn_values(runs) == {"contradiction": 2, "premise": 1}
    assert H.string_turn_values(runs[1:2]) == {"contradiction": 0, "premise": 0}


# ------------------------------------------------------------------ the bootstrap and the size


def hand_quantile(sorted_values: list[float], q: float) -> float:
    """numpy's default (linear) quantile, by hand."""
    h = (len(sorted_values) - 1) * q
    low = math.floor(h)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (h - low) * (sorted_values[high] - sorted_values[low])


def hand_bootstrap(values: list[float]) -> tuple[float, float, float]:
    rng = np.random.default_rng(20261130)
    draws = rng.integers(0, len(values), size=(10_000, len(values))).tolist()
    means = sorted(sum(values[j] for j in row) / len(values) for row in draws)
    return sum(values) / len(values), hand_quantile(means, 0.025), hand_quantile(means, 0.975)


def test_the_bootstrap_matches_a_hand_computation_on_a_toy():
    toy = [0.0, 1 / 3, -2 / 3, 1.0]
    mean, low, high = H.bootstrap_ci(toy, H.resample_matrix(len(toy)))
    hand = hand_bootstrap(toy)
    assert mean == pytest.approx(hand[0], abs=1e-12)
    assert low == pytest.approx(hand[1], abs=1e-12)
    assert high == pytest.approx(hand[2], abs=1e-12)
    assert low < mean < high


# Recovered repeats out of 3, per world, arm and form, for a fake trap of three worlds.
TABLE = {
    0: {"R0": (2, 2), "R1": (1, 3), "R2": (3, 2)},
    1: {"R0": (1, 1), "R1": (0, 2), "R2": (1, 1)},
    2: {"R0": (3, 3), "R1": (3, 3), "R2": (2, 3)},
}


def fake_runs(trap: int) -> list[dict]:
    runs = []
    for w, row in TABLE.items():
        for arm, (trapped, twin) in row.items():
            for form, hits in (("trapped", trapped), ("twin", twin)):
                for repeat in range(3):
                    runs.append(
                        {
                            "trap": trap, "w": w, "form": form, "arm": arm, "repeat": repeat, "seed": repeat,
                            "recovered": repeat < hits, "turns": 7, "calls": 7, "faults": 0, "reruns": 0,
                            "stalls": {}, "usage": {"input_tokens": 100}, "seconds": 1.0,
                            "named": (repeat == 0) if form == "trapped" else None,
                            "raised": True if form == "trapped" else None,
                            "false_named": (repeat == 1) if form == "twin" else None,
                            "firing": [1] if repeat == 0 else [], "distinct_indices": 4,
                        }
                    )  # fmt: skip
    return runs


def test_score_computes_the_six_differences_per_world_and_bootstraps_each_with_the_traps_fresh_matrix():
    report = H.score(fake_runs(2) + fake_runs(5))
    rate = {(w, arm, form): hits / 3 for w, row in TABLE.items() for arm, pair in row.items()
            for form, hits in zip(("trapped", "twin"), pair)}  # fmt: skip

    def effect(w, arm):
        return rate[(w, arm, "trapped")] - rate[(w, arm, "twin")]

    by_hand = {
        "fall_in/R1-R0": [effect(w, "R1") - effect(w, "R0") for w in TABLE],
        "fall_in/R2-R0": [effect(w, "R2") - effect(w, "R0") for w in TABLE],
        "get_out/R1-R0": [rate[(w, "R1", "trapped")] - rate[(w, "R0", "trapped")] for w in TABLE],
        "get_out/R2-R0": [rate[(w, "R2", "trapped")] - rate[(w, "R0", "trapped")] for w in TABLE],
        "fall_in/R2-R1": [effect(w, "R2") - effect(w, "R1") for w in TABLE],
        "get_out/R2-R1": [rate[(w, "R2", "trapped")] - rate[(w, "R1", "trapped")] for w in TABLE],
    }
    # World 0, by the spec's words: R1's trap effect is 1/3 - 1, R0's is 0.
    assert by_hand["fall_in/R1-R0"][0] == pytest.approx(-2 / 3)
    for trap in (2, 5):
        prim = report["traps"][trap]["primaries"]
        assert set(prim) == set(by_hand)
        for name, values in by_hand.items():
            mean, low, high = hand_bootstrap(values)
            assert list(prim[name]["per_world"].values()) == pytest.approx(values)
            assert prim[name]["mean"] == pytest.approx(mean)
            assert prim[name]["ci"] == pytest.approx([low, high], abs=1e-12)
            assert prim[name]["sd"] == pytest.approx(float(np.std(values, ddof=1)))
    assert report["traps"][2]["primaries"] == report["traps"][5]["primaries"]  # fresh per trap, not continued
    assert report["traps"][2]["primaries"]["fall_in/R1-R0"]["expected_sign"] == "negative"
    assert report["traps"][2]["primaries"]["get_out/R2-R0"]["expected_sign"] == "positive"
    assert report["traps"][2]["primaries"]["get_out/R2-R1"]["expected_sign"] is None
    sigma = max(float(np.std(v, ddof=1)) for v in by_hand.values())
    assert report["traps"][2]["size"] == H.pilot_size(sigma)


def test_score_reports_naming_beside_with_false_names_activity_and_counts():
    report = H.score(fake_runs(1) + fake_runs(3))
    one, three = report["traps"][1], report["traps"][3]
    assert one["naming"]["rule"] == "named" and three["naming"]["rule"] == "raised"
    assert set(one["naming"]["arms"]) == {"R1", "R2"}  # only exposed runs are scored
    assert one["naming"]["arms"]["R1"] == {
        "trapped_runs": 9, "scored": 9, "unscored": 0, "named": 3, "rate": 1 / 3, "raised": 9,
    }  # fmt: skip
    assert three["naming"]["arms"]["R2"]["named"] == 9  # trap 3 counts raised
    assert one["false_names"]["R0"] == {"twin_runs": 9, "false_names": 3, "rate": 1 / 3}
    assert one["activity"]["R1"]["trapped"] == {"runs": 5, "mean_distinct_indices": 4.0}
    assert one["firing"]["R2"]["twin"]["runs_firing"] == 3
    assert report["per_arm"]["R0"]["runs"] == 36 and report["per_arm"]["R0"]["usage"] == {"input_tokens": 3600}


def test_the_pilot_size_formula():
    assert H.pilot_size(0.30)["N"] == 16
    assert H.pilot_size(0.05) == {"sigma_raw": 0.05, "sigma": 0.30, "N": 16, "worlds_to_run": 16, "passes_20": False}
    big = H.pilot_size(0.5)
    assert big["N"] == math.ceil((2 * 1.96 * 0.5 / 0.30) ** 2) == 43
    assert big["worlds_to_run"] == 20 and big["passes_20"] is True
    assert H.pilot_size(None)["N"] is None


def test_provenance_names_the_three_modules_the_fingerprint_and_numpy():
    found = H.provenance()
    for module in (W, A, H):
        name = Path(module.__file__).name
        assert found[name] == hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    assert found["fingerprint"] == W.fingerprint() and found["numpy"] == np.__version__


def test_the_arm_order_is_drawn_per_world_and_repeat():
    for trap in (1, 2, 3, 4, 5):
        for w in (0, 1, 2):
            for repeat in (0, 1, 2):
                drawn = np.random.default_rng([20261202, trap, w, repeat]).permutation(3)
                assert H.arm_order(trap, w, repeat) == [["R0", "R1", "R2"][int(k)] for k in drawn]
    orders = {tuple(H.arm_order(t, w, r)) for t in (1, 2, 3, 4, 5) for w in (0, 1, 2) for r in (0, 1, 2)}
    assert len(orders) > 1  # the pilot doesn't always run R0, R1, R2


def test_a_stopped_series_restarts_whole():
    assert "restarted whole" in H.RESTART_RULE and "never" in H.RESTART_RULE
    assert "restarts whole" in H.MachineDown.__doc__
    assert H.score(fake_runs(1))["restart_rule"] == H.RESTART_RULE


def test_the_pilot_is_270_runs():
    pilot = H.select_worlds(ALL)
    assert len(pilot) == 30 and {w["w"] for w in pilot} == {0, 1, 2}
    assert len(pilot) * len(H.ARMS) * len(H.PILOT_REPEATS) == 270


# ------------------------------------------------------------------ the frozen invocation (built, never run)


CL = "/home/doctor/.local/share/claude/versions/2.1.330"
FROZEN_ARGV = [
    "systemd-run", "--user", "--scope", "--unit=t4b-turn-test", "--",
    "timeout", "120",
    "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
    "--tmpfs", "/tmp", "--tmpfs", "/var/tmp", "--tmpfs", "/home/doctor",
    "--ro-bind", CL, CL,
    "--ro-bind", "/home/doctor/.local/bin/uv", "/home/doctor/.local/bin/uv",
    "--ro-bind", "/home/doctor/.local/bin/uvx", "/home/doctor/.local/bin/uvx",
    "--bind", "/var/tmp/t4b-turn", "/var/tmp/t4b-turn",
    "--bind", "/var/tmp/t4b-home", "/var/tmp/t4b-home",
    "--bind", "/var/tmp/t4b-config", "/var/tmp/t4b-config",
    "--chdir", "/var/tmp/t4b-turn", "--die-with-parent", "--unshare-pid", "--",
    "env", "-i", "PATH=/home/doctor/.local/bin:/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "TERM=dumb", "TZ=UTC",
    "HOME=/var/tmp/t4b-home/home", "UV_CACHE_DIR=/var/tmp/t4b-home/uv-cache", "CLAUDE_CONFIG_DIR=/var/tmp/t4b-config",
    "GIT_SSH_COMMAND=false",
    CL, "-p", "THE PROMPT",
    "--model", "claude-sonnet-5-5", "--output-format", "stream-json", "--verbose",
    "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
]  # fmt: skip


def after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_the_frozen_argv():
    argv = H.turn_argv("THE PROMPT", unit="t4b-turn-test")
    assert argv == FROZEN_ARGV
    claude = argv[argv.index("GIT_SSH_COMMAND=false") + 1:]
    assert after(claude, "--tools") == ""
    assert "--strict-mcp-config" in claude and after(claude, "--mcp-config") == '{"mcpServers":{}}'
    assert after(claude, "--model") == "claude-sonnet-5-5"
    assert after(argv, "--chdir") == "/var/tmp/t4b-turn"
    assert after(argv, "timeout") == "120"
    for refused in ("--allowedTools", "--allowed-tools", "--permission-mode", "--dangerously-skip-permissions"):
        assert not any(a == refused or a.startswith(refused + "=") for a in argv)
    assert after(claude, "-p") == "THE PROMPT"


def test_only_the_prompt_varies_and_the_working_directory_is_fixed():
    a = H.turn_argv("prompt one", unit="u")
    b = H.turn_argv("a different prompt, any world", unit="u")
    assert [x for x, y in zip(a, b) if x != y] == ["prompt one"]
    assert H.FROZEN.turn_dir == "/var/tmp/t4b-turn" and H.FROZEN.timeout == 120


def test_reset_config_keeps_only_the_sign_ins_files(tmp_path):
    (tmp_path / ".credentials.json").write_text("{}")
    (tmp_path / ".claude.json").write_text("{}")
    (tmp_path / "projects" / "x").mkdir(parents=True)
    (tmp_path / "projects" / "x" / "session.jsonl").write_text("old")
    (tmp_path / "statsig").mkdir()
    (tmp_path / "statsig" / "keep.me").write_text("1")
    (tmp_path / "statsig" / "drop.me").write_text("1")
    deleted = H.reset_config(tmp_path, [".credentials.json", ".claude.json", "statsig/keep.me"])
    left = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert left == [".claude.json", ".credentials.json", "statsig", "statsig/keep.me"]
    assert "projects/x/session.jsonl" in deleted and "projects" in deleted
    with pytest.raises(H.HarnessStop):
        H.reset_config(tmp_path, [".credentials.json", "missing.json"])


# ------------------------------------------------------------------ one end-to-end pilot slice, through the stub


class SliceStub:
    """Deterministic canned turns: mostly JSON replies chosen by the prompt's hash, with malformed replies,
    timeouts, single faults, and one double fault that voids a run."""

    def __init__(self):
        self.k = 0
        self.kinds: Counter[str] = Counter()

    def __call__(self, prompt: str) -> H.TurnResult:
        k = self.k
        self.k += 1
        h = int(hashlib.sha256(prompt.encode()).hexdigest(), 16)
        if k in (40, 41) or k % 17 == 3:
            out = H.TurnResult.fault("result is_error", usage={"input_tokens": 0})
        elif k % 13 == 7:
            out = H.TurnResult.stall("timeout", seconds=120.0)
        elif k % 11 == 5:
            out = H.TurnResult.reply("I'd choose patch 2.", usage={"input_tokens": 2000, "output_tokens": 40})
        else:
            flags = [] if h % 3 else [{"repeat": (h // 7) % 5}]
            body = json.dumps({"choice": h % 5, "summary": "Chose by the stub's hash.", "flags": flags})
            out = H.TurnResult.reply(body, usage={"input_tokens": 2000, "output_tokens": 60}, seconds=11.0)
        self.kinds["malformed" if out.text == "I'd choose patch 2." else out.kind] += 1
        return out


def test_a_pilot_slice_end_to_end_through_the_stub():
    worlds = H.select_worlds(ALL, ws=(0,))
    assert len(worlds) == 10
    stub = SliceStub()
    pauses = []
    runs = H.run_series(worlds, call_turn=stub, repeats=(0,), pause=pauses.append)
    report = H.score(runs)
    json.dumps(report)  # the report is plain JSON

    assert report["runs"] == len(runs) == 30
    assert {(r["trap"], r["form"], r["arm"]) for r in runs} == {
        (t, f, a) for t in (1, 2, 3, 4, 5) for f in ("trapped", "twin") for a in ("R0", "R1", "R2")
    }
    assert sorted(report["traps"]) == [1, 2, 3, 4, 5]
    for trap, section in report["traps"].items():
        assert section["worlds"] == [0]
        assert set(section["primaries"]) == {name for name, *_ in H.PRIMARIES}
        for p in section["primaries"].values():
            low, high = p["ci"]
            assert low <= p["mean"] <= high  # one world: the CI is that world's value
            assert p["sd"] is None
        assert section["size"]["N"] is None  # one world gives no ddof = 1 deviation
        assert section["naming"]["rule"] == ("raised" if trap == 3 else "named")
        assert set(section["naming"]["arms"]) == {"R1", "R2"}
        assert set(section["false_names"]) == {"R0", "R1", "R2"}
        for block in ("recovery", "activity", "firing"):
            assert set(section[block]) == {"R0", "R1", "R2"}
            assert all(set(v) == {"trapped", "twin"} for v in section[block].values())
        assert all(section["recovery"][a][f]["runs"] == 1 for a in H.ARMS for f in H.FORMS)

    per_arm = report["per_arm"]
    assert set(per_arm) == {"R0", "R1", "R2"}
    assert sum(a["faults"] for a in per_arm.values()) == stub.kinds["fault"]
    assert sum(a["reruns"] for a in per_arm.values()) == 1
    assert sum(a["calls"] for a in per_arm.values()) == stub.k
    stalls = sum(a["stalls"] + a["stalls_in_voided_attempts"] for a in per_arm.values())
    assert stalls == stub.kinds["stall"] + stub.kinds["malformed"] > 0
    assert sum(a["stalls_by_reason"].get("malformed", 0) for a in per_arm.values()) > 0
    assert len(pauses) == stub.kinds["fault"] - 1  # every fault pauses but the one that voided
    for arm, block in per_arm.items():  # stalls per arm and per form
        assert set(block["by_form"]) == {"trapped", "twin"}
        for name in ("runs", "stalls", "stalls_in_voided_attempts", "faults", "reruns"):
            assert sum(block["by_form"][f][name] for f in H.FORMS) == block[name]
        assert set(block["string_turn_values"]) == {"contradiction", "premise"}
    assert report["string_turn_values"] == {"contradiction": 0, "premise": 0}  # the stub sends only repeat flags

    # The arms ran in each world's drawn order, both forms alike, and the report records every order.
    assert report["arm_orders"] == [
        {"trap": t, "w": 0, "repeat": 0, "order": H.arm_order(t, 0, 0)} for t in (1, 2, 3, 4, 5)
    ]
    assert [r["position"] for r in runs] == list(range(30))
    for k, wd in enumerate(worlds):
        block = runs[3 * k : 3 * k + 3]
        assert all(r["trap"] == wd["trap"] and r["form"] == wd["form"] for r in block)
        assert [r["arm"] for r in block] == H.arm_order(wd["trap"], wd["w"], 0) == block[0]["arm_order"]
    assert report["restart_rule"] == H.RESTART_RULE
    for r in runs:
        n = len(world(r["trap"], r["w"], r["form"])["planted"])
        turns = [e["turn"] for e in r["record"][n:]]
        assert turns == sorted(set(turns)) and all(n < t <= n + 7 for t in turns)
        assert r["turns"] <= 7 and len(r["flags_per_call"]) == len(r["record"])
