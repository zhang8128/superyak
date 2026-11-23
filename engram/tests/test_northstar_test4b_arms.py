"""Test 4, stage B, the arms' half: prompts per arm, R2's advice from stage A's content policy, and the reply reader.
Written with a toy task here, never a stage B world's code."""
from __future__ import annotations

import pytest

from experiments.northstar import test4b_arms as arms

TASK = "Make `median(xs)` return the median of a list of numbers; the frozen test checks odd and even lengths."
PATCHES = [{"description": "average the two middle values for even lengths", "diff": "-a\n+b"},
           {"description": "use the mean", "diff": "-a\n+c"},
           {"description": "take the lower middle value", "diff": "-a\n+d"}]
RECORD = [{"turn": 1, "description": "use the arithmetic mean", "diff": "-a\n+c", "verdict": "fail",
           "summary": "The mean failed on [1, 2, 10]."}]
KEYS = ["k-mean", "k-mid", "k-mean", "k-low"]        # the record entry's key, then each open patch's


def test_R0_gives_the_task_and_patches_but_no_record_or_advice():
    text = arms.prompt("R0", TASK, PATCHES, RECORD)
    assert TASK in text and "Patch 2: take the lower middle value" in text
    assert "record" not in text.split("The open patches")[1].split("Reply with")[0].lower()
    assert "Advice" not in text and "except what the record" not in text


def test_R1_adds_the_record_with_diffs_and_no_content_keys():
    text = arms.prompt("R1", TASK, PATCHES, RECORD, keys=KEYS)
    assert 'Turn 1: tried "use the arithmetic mean"' in text and "Verdict from the frozen test: fail" in text
    assert "-a\n+c" in text and not any(k in text for k in set(KEYS)) and "Advice" not in text


def test_R2_adds_the_content_policys_advice_and_names_the_repeat():
    text = arms.prompt("R2", TASK, PATCHES, RECORD, keys=KEYS, seed=0)
    assert "Advice from a bandit" in text and "patch 1 changes exactly what an earlier turn's patch did" in text
    assert not any(k in text for k in set(KEYS))        # keys drive the advice, but never appear in it


def test_an_unchecked_entry_is_shown_as_such_and_left_out_of_R2s_counts():
    record = [{"turn": 1, "description": "average the middle", "diff": "-a\n+b", "verdict": None,
               "summary": "Timed out."}]
    text = arms.prompt("R2", TASK, PATCHES, record, keys=["k-mid", "k-mid", "k-mean", "k-low"])
    assert "none (its turn ended before the test ran)" in text
    assert "changes exactly what" not in text           # never tried, so not a repeat


def test_the_reader_takes_the_frozen_shape_and_refuses_anything_else():
    assert arms.read_reply('{"choice": 2, "summary": "Try the lower middle.", "flags": []}', 3) == (
        2, "Try the lower middle.", [])
    assert arms.read_reply('```json\n{"choice": 0, "summary": "s", "flags": [{"repeat": "1"}]}\n```', 3)[2] == [
        {"repeat": "1"}]
    for bad in ('choice 2', '{"choice": 3, "summary": "s", "flags": []}', '{"choice": "1", "summary": "s", "flags": []}',
                '{"choice": 1, "summary": "", "flags": []}', '{"choice": 1, "summary": "s"}',
                '{"choice": 1, "summary": "s", "flags": [{"other": 1}]}', 'Sure! {"choice": 1, "summary": "s", "flags": []}',
                '{"choice": 1, "summary": "s", "flags": [], "extra": 1}'):
        with pytest.raises(arms.Malformed):
            arms.read_reply(bad, 3)


def test_an_unknown_arm_is_refused():
    with pytest.raises(ValueError):
        arms.prompt("R3", TASK, PATCHES, RECORD)
