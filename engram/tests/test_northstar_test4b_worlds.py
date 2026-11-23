"""Tests for the Test 4b world half (five traps whose approaches are patches).

These are the world half's own tests, as "The worlds" lists them:
- one pass: on every base only patch p passes the frozen test, the base
  fails, and the generator agrees; each base's keys are distinct, and so are
  all 40 of trap 4's; `patch -p1` on the base gives each patched file exactly;
- twins: a trapped layout differs from its twin in exactly its trap's fields;
- rebuilt: each world is identical when rebuilt from its seed;
- recovery: the oracle applies p at the first run turn, and a record-only
  reader recovers within 7, in both forms of every world;
- naming: each rule fires on a hand-built run that raises its flag at the
  named call, and not one call later, one call earlier, or in the twin.

The oracle, the record-only reader and the little run harness here are
written for these tests alone; no arm or harness is used. Verdicts here come
from running the frozen test: in-process on every file, and through the
verdict command itself (a subprocess pytest per file) on the pilot worlds,
or on every world when T4B_VERDICT_ALL=1.
"""

import difflib
import functools
import hashlib
import os
import subprocess
import sys
import tempfile
import types
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from experiments.northstar import test4b_worlds as tw

TRAPS = (1, 2, 3, 4, 5)
FORMS = ("trapped", "twin")
PILOT_W = (0, 1, 2)
LAYOUT_KEYS = {
    "trap", "w", "form", "budget", "passing", "task", "test", "bases", "names", "patches", "planted",
}
ENTRY_KEYS = {
    "turn", "state", "index", "name", "diff", "content", "verdict", "summary", "says", "observation",
}
FUNCTION_NAMES = [
    "fold_counts", "mix_tally", "ledger_sum", "score_rows",
    "pack_marks", "blend_bins", "trail_check", "vote_digest",
]
WORDS = (
    "amber basin cedar delta ember fjord garnet harbor iris jasper kestrel lantern meadow nectar "
    "onyx pepper quarry raven saffron timber umber velvet willow xenon yarrow zephyr acorn birch "
    "cobalt dune elm flint grove heron indigo juniper kelp lichen maple nickel oak pine quartz "
    "reed slate thistle upland vale walnut yew zinc alder bramble clover dahlia egret fern gorse "
    "hazel ivy jade kiln lupin moss"
).split()
assert len(WORDS) == 64


# ---------------------------------------------------------------------------
# Test-only helpers, written from the brief
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _worlds():
    return tw.worlds()


@functools.lru_cache(maxsize=1)
def _by_key():
    return {(wd["trap"], wd["w"], wd["form"]): wd for wd in _worlds()}


def _pair(trap, w):
    by = _by_key()
    return by[(trap, w, "trapped")], by[(trap, w, "twin")]


@functools.lru_cache(maxsize=None)
def _draw(trap, w):
    """The nine draws, in the brief's order, drawn here independently."""
    rng = np.random.default_rng(np.random.SeedSequence([20261201, trap, w]))
    fn = int(rng.integers(8))
    words = [int(x) for x in rng.choice(64, size=5, replace=False)]
    mult = [int(x) for x in rng.integers(2, 100, size=5)]
    offset = [int(x) for x in rng.choice(np.arange(1, 50), size=5, replace=False)]
    modulus = [int(x) for x in rng.integers(1000, 10000, size=5)]
    p = int(rng.integers(5))
    inputs = rng.integers(0, 100, size=(7, 6)).tolist()
    rev = [f"{int(x):06x}" for x in rng.integers(0, 16**6, size=8)]
    order = [int(x) for x in rng.permutation([i for i in range(5) if i != p])]
    return {
        "fn": FUNCTION_NAMES[fn], "words": [WORDS[x] for x in words], "word_ids": words,
        "mult": mult, "offset": offset, "modulus": modulus, "p": p, "inputs": inputs,
        "rev": rev, "order": order,
    }


def _base(fn, rev, j):
    head = f'"""{fn}: fold a list of counts into one checksum."""\n'
    revisions = "".join(f"# Revision {rev[k]}.\n" for k in range(j + 1))
    body = (
        "\n"
        "MULTIPLIER = 1\n"
        "OFFSET = 0\n"
        "MODULUS = 10007\n"
        "\n"
        f"def {fn}(values):\n"
        "    total = 0\n"
        "    for i, v in enumerate(values):\n"
        "        total = (total * MULTIPLIER + v * (i + OFFSET)) % MODULUS\n"
        "    return total\n"
    )
    return head + revisions + body


def _patched(base, m, o, mod):
    out = base.replace("\nMULTIPLIER = 1\n", f"\nMULTIPLIER = {m}\n", 1)
    out = out.replace("\nOFFSET = 0\n", f"\nOFFSET = {o}\n", 1)
    out = out.replace("\nMODULUS = 10007\n", f"\nMODULUS = {mod}\n", 1)
    return out


def _normalized_key(text):
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _files(world):
    """[(base, [patched file of patch 0..4])] for each of the world's bases,
    rebuilt here from the draws."""
    d = _draw(world["trap"], world["w"])
    out = []
    for base in world["bases"]:
        out.append((base, [_patched(base, d["mult"][i], d["offset"][i], d["modulus"][i]) for i in range(5)]))
    return out


def _files_by_key(world):
    return {_normalized_key(text): text for _, texts in _files(world) for text in texts}


def _frozen_passes(target_text, test_text):
    """Runs the frozen test's own code, in-process, against target_text."""
    module = types.ModuleType("target")
    exec(compile(target_text, "target.py", "exec"), module.__dict__)
    saved = sys.modules.get("target")
    sys.modules["target"] = module
    try:
        namespace = {"__name__": "test_target"}
        exec(compile(test_text, "test_target.py", "exec"), namespace)
        tests = [v for k, v in namespace.items() if k.startswith("test_") and callable(v)]
        assert len(tests) == 1
        try:
            tests[0]()
        except AssertionError:
            return False
        return True
    finally:
        if saved is None:
            sys.modules.pop("target", None)
        else:
            sys.modules["target"] = saved


def _changed(diff):
    return [
        line for line in diff.splitlines()
        if line[:1] in ("+", "-") and not line.startswith(("+++ ", "--- "))
    ]


def _entry(world, record, i, x, files):
    """Run turn i applies open patch x; its verdict comes from running the
    frozen test on the file whose key the open patch shows."""
    opened = tw.open_patches(world, record, i)
    patch = opened[x]
    passed = _frozen_passes(files[patch["content"]], world["test"])
    return {
        "turn": len(world["planted"]) + i,
        "state": "G" if passed else f"S{min(i + 1, len(world['bases']) - 1)}",
        "index": x,
        "name": patch["name"],
        "diff": patch["diff"],
        "content": patch["content"],
        "verdict": "pass" if passed else "fail",
        "summary": "Applied a patch.",
        "says": None,
        "observation": None,
    }


def _run(world, chooser):
    """Up to 7 run turns after the planted ones. Returns (record, the run
    turn that passed or None)."""
    files = _files_by_key(world)
    record = [dict(e) for e in world["planted"]]
    for i in range(1, world["budget"] + 1):
        record.append(_entry(world, record, i, chooser(world, record, i), files))
        if record[-1]["verdict"] == "pass":
            return record, i
    return record, None


def _hand_run(world, choices):
    files = _files_by_key(world)
    record = [dict(e) for e in world["planted"]]
    for i, x in enumerate(choices, start=1):
        record.append(_entry(world, record, i, x, files))
    return record


def _oracle(world, record, i):
    return world["passing"]


def _record_only_reader(world, record, i):
    failed = [_changed(e["diff"]) for e in record if e["verdict"] == "fail"]
    for x, patch in enumerate(tw.open_patches(world, record, i)):
        if _changed(patch["diff"]) not in failed:
            return x
    raise AssertionError("every open patch matches a failed entry")


def _name(word):
    return f"The {word} patch: retune MULTIPLIER, OFFSET and MODULUS."


# ---------------------------------------------------------------------------
# One pass
# ---------------------------------------------------------------------------

def test_exactly_one_patch_passes_on_every_base_and_the_base_fails():
    problems = []
    for world in _worlds():
        d = _draw(world["trap"], world["w"])
        if world["passing"] != d["p"]:
            problems.append((world["trap"], world["w"], world["form"], "passing"))
        for j, (base, texts) in enumerate(_files(world)):
            if _frozen_passes(base, world["test"]):
                problems.append((world["trap"], world["w"], world["form"], j, "base passes"))
            passing = [i for i, text in enumerate(texts) if _frozen_passes(text, world["test"])]
            if passing != [world["passing"]]:
                problems.append((world["trap"], world["w"], world["form"], j, passing))
    assert not problems, problems[:10]


def _verdict_jobs(ws):
    jobs = {}
    for world in ws:
        for base, texts in _files(world):
            jobs[(base, world["test"])] = "fail"
            for i, text in enumerate(texts):
                jobs[(text, world["test"])] = "pass" if i == world["passing"] else "fail"
    return jobs


def test_the_verdict_command_agrees():
    """The harness's own command, a fresh directory per file. The pilot
    worlds by default; every world with T4B_VERDICT_ALL=1."""
    every = os.environ.get("T4B_VERDICT_ALL") == "1"
    ws = [wd for wd in _worlds() if every or wd["w"] in PILOT_W]
    jobs = _verdict_jobs(ws)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        got = list(pool.map(lambda job: tw.verdict(*job), jobs))
    wrong = [(want, have) for want, have in zip(jobs.values(), got) if want != have]
    assert not wrong, (len(wrong), len(jobs))
    assert {"pass", "fail"} == set(got)


def test_keys_are_the_normalized_sha256_and_distinct():
    for world in _worlds():
        files = _files(world)
        assert len(world["patches"]) == len(world["bases"]) == len(files)
        for j, (base, texts) in enumerate(files):
            keys = [_normalized_key(text) for text in texts]
            assert [p["content"] for p in world["patches"][j]] == keys
            assert len(set(keys)) == 5
            assert _normalized_key(base) not in keys
        if world["trap"] == 4 and world["form"] == "trapped":
            all_keys = [p["content"] for row in world["patches"] for p in row]
            assert len(all_keys) == 40 and len(set(all_keys)) == 40


def test_whitespace_and_line_endings_dont_split_a_key():
    world = _worlds()[0]
    text = _files(world)[0][1][0]
    variant = text.replace("\n", "  \r\n") + "\r\n\n   \n"
    assert tw.key(variant) == tw.key(text) == _normalized_key(text)
    assert tw.key(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def _apply_patch(job):
    base, diff = job
    with tempfile.TemporaryDirectory(prefix="t4b-patch-") as tmp:
        path = os.path.join(tmp, "target.py")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(base)
        proc = subprocess.run(["patch", "-p1"], cwd=tmp, input=diff, text=True, capture_output=True)
        with open(path, encoding="utf-8", newline="") as fh:
            return proc.returncode, fh.read()


def test_patch_p1_on_the_base_gives_each_patched_file_exactly():
    jobs = {}
    for world in _worlds():
        for j, (base, texts) in enumerate(_files(world)):
            for i, text in enumerate(texts):
                diff = world["patches"][j][i]["diff"]
                expected = "".join(difflib.unified_diff(
                    base.splitlines(True), text.splitlines(True), "a/target.py", "b/target.py"))
                assert diff == expected
                jobs[(base, diff)] = text
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        results = list(pool.map(_apply_patch, jobs))
    bad = [n for n, ((code, out), want) in enumerate(zip(results, jobs.values())) if code != 0 or out != want]
    assert not bad, (len(bad), len(jobs))


# ---------------------------------------------------------------------------
# The layout follows the nine draws
# ---------------------------------------------------------------------------

def test_worlds_are_the_thousand_sorted_and_laid_out():
    ws = _worlds()
    assert len(ws) == 1000
    assert [(wd["trap"], wd["w"], wd["form"]) for wd in ws] == [
        (t, w, f) for t in TRAPS for w in range(100) for f in FORMS]
    for wd in ws:
        assert set(wd) == LAYOUT_KEYS
        assert wd["budget"] == 7
        assert len(wd["names"]) == 5
        for row in wd["patches"]:
            assert len(row) == 5 and all(set(p) == {"diff", "content"} for p in row)
        for e in wd["planted"]:
            assert set(e) == ENTRY_KEYS
            assert e["observation"] is None
            assert e["state"] != "G"


def test_each_world_follows_its_nine_draws():
    for wd in _worlds():
        trap, form = wd["trap"], wd["form"]
        d = _draw(trap, wd["w"])
        fn, p, order, words = d["fn"], d["p"], d["order"], d["words"]
        assert wd["passing"] == p
        assert wd["task"] == (
            f"`target.py` defines `{fn}(values)`, which must match a reference implementation on "
            "the frozen test's fixed inputs. Its three constants are wrong, and each candidate patch "
            "sets all three.")
        inputs = [[1]] + d["inputs"]
        outputs = [
            _fold(values, d["mult"][p], d["offset"][p], d["modulus"][p]) for values in inputs]
        digest = hashlib.sha256(repr(outputs).encode()).hexdigest()
        assert wd["test"] == "".join(line + "\n" for line in [
            "import hashlib",
            f"from target import {fn}",
            f"INPUTS = {inputs!r}",
            f'DIGEST = "{digest}"',
            f"def test_{fn}():",
            f"    outputs = [{fn}(values) for values in INPUTS]",
            "    assert hashlib.sha256(repr(outputs).encode()).hexdigest() == DIGEST",
        ])
        assert wd["test"].count("\n") == 7
        versions = 8 if (trap == 4 and form == "trapped") else 1
        assert wd["bases"] == [_base(fn, d["rev"], j) for j in range(versions)]
        spares = [WORDS[x] for x in range(64) if x not in d["word_ids"]]
        assert len(spares) == 59
        for i in range(5):
            if trap == 1 and form == "trapped" and i == order[0]:
                assert wd["names"][i] == [_name(words[i])] + [_name(s) for s in spares[:7]]
            else:
                assert wd["names"][i] == [_name(words[i])]

        n = {1: 1, 2: 1, 3: 3, 4: 2, 5: 5 if form == "trapped" else 4}[trap]
        planted = wd["planted"]
        assert [e["turn"] for e in planted] == list(range(1, n + 1))
        fail = "Applied the {} patch. The test failed."
        for t, e in enumerate(planted, start=1):
            x = e["index"]
            assert e["name"] == wd["names"][x][0]
            assert e["diff"] == wd["patches"][0][x]["diff"]
            assert e["content"] == wd["patches"][0][x]["content"]
            want_state = "S1" if (trap == 4 and form == "trapped" and t == 2) else "S0"
            assert e["state"] == want_state
            if trap == 5 and t == 5:
                assert (x, e["verdict"], e["summary"], e["says"]) == (p, None, None, None)
                continue
            assert x == order[t - 1]
            assert e["verdict"] == "fail"
            summary = fail.format(words[x])
            says = "failed"
            if trap == 2 and form == "trapped":
                summary, says = f"Applied the {words[x]} patch. It worked.", "worked"
            if trap == 3 and (t < 3 or form == "trapped"):
                summary += f" Try the {words[order[t % 3]]} patch next."
            assert (e["summary"], e["says"]) == (summary, says)


def _fold(values, m, o, mod):
    total = 0
    for i, v in enumerate(values):
        total = (total * m + v * (i + o)) % mod
    return total


# ---------------------------------------------------------------------------
# Twins
# ---------------------------------------------------------------------------

def _differences(a, b):
    paths = set()
    for k in sorted(set(a) | set(b)):
        if k == "form":
            continue
        if k == "names":
            assert len(a[k]) == len(b[k]) == 5
            paths |= {("names", i) for i in range(5) if a[k][i] != b[k][i]}
        elif k == "planted":
            ta = {e["turn"]: e for e in a[k]}
            tb = {e["turn"]: e for e in b[k]}
            for t in sorted(set(ta) | set(tb)):
                if t not in ta or t not in tb:
                    paths.add(("planted", t))
                else:
                    paths |= {("planted", t, f) for f in ENTRY_KEYS if ta[t][f] != tb[t][f]}
        elif a.get(k) != b.get(k):
            paths.add((k,))
    return paths


def test_twins_differ_in_exactly_their_traps_fields():
    for trap in TRAPS:
        for w in range(100):
            trapped, twin = _pair(trap, w)
            r = trapped["planted"][0]["index"]
            expected = {
                1: {("names", r)},
                2: {("planted", 1, "summary"), ("planted", 1, "says")},
                3: {("planted", 3, "summary")},
                4: {("bases",), ("patches",), ("planted", 2, "state")},
                5: {("planted", 5)},
            }[trap]
            assert _differences(trapped, twin) == expected, (trap, w)
            if trap == 1:
                assert twin["names"][r] == trapped["names"][r][:1]
            if trap == 4:
                assert twin["bases"] == trapped["bases"][:1]
                assert twin["patches"] == trapped["patches"][:1]
            if trap == 5:
                assert twin["planted"] == trapped["planted"][:4]


# ---------------------------------------------------------------------------
# Rebuilt
# ---------------------------------------------------------------------------

def test_each_world_rebuilds_identically_from_its_seed():
    for trap in TRAPS:
        for w in range(100):
            assert tw.build_pair(trap, w) == tw.build_pair(trap, w) == _pair(trap, w)
    assert tw.fingerprint() == tw.fingerprint(_worlds())


# The fingerprint posted with this implementation (numpy 2.4.3). numpy doesn't
# promise its stream across versions, so another version skips this check.
POSTED_FINGERPRINT = "015f4ffb2b35d753a6d4acdd69c007ec940e16685d0634320c4179cc8f51c046"


def test_fingerprint_matches_the_posted_value():
    if np.__version__ != "2.4.3":
        pytest.skip(f"the posted fingerprint is numpy 2.4.3's, not {np.__version__}'s")
    assert tw.fingerprint(_worlds()) == POSTED_FINGERPRINT


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def test_open_patches_are_all_five_in_index_order_on_the_turns_base():
    for wd in _worlds():
        record = [dict(e) for e in wd["planted"]]
        for i in (1, 2, 7, 9):
            opened = tw.open_patches(wd, record, i)
            j = min(i, len(wd["bases"]) - 1)
            assert [set(o) for o in opened] == [{"name", "diff", "content"}] * 5
            assert [o["content"] for o in opened] == [p["content"] for p in wd["patches"][j]]
            assert [o["diff"] for o in opened] == [p["diff"] for p in wd["patches"][j]]
            counts = [sum(1 for e in record if e["index"] == x) for x in range(5)]
            assert [o["name"] for o in opened] == [
                wd["names"][x][min(counts[x], len(wd["names"][x]) - 1)] for x in range(5)]


def test_the_oracle_applies_p_and_recovers_at_the_first_run_turn():
    for wd in _worlds():
        record, turn = _run(wd, _oracle)
        assert turn == 1, (wd["trap"], wd["w"], wd["form"])
        assert record[-1]["index"] == wd["passing"]


def test_the_record_only_reader_recovers_within_seven():
    slow = []
    for wd in _worlds():
        record, turn = _run(wd, _record_only_reader)
        if turn is None:
            slow.append((wd["trap"], wd["w"], wd["form"]))
    assert not slow, slow[:10]


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def _right_values(world):
    planted = world["planted"]
    base0 = world["patches"][0]
    trap = world["trap"]
    if trap == 1:
        return [base0[planted[0]["index"]]["content"]]
    if trap == 2:
        return [1]
    if trap == 3:
        return [base0[e["index"]]["content"] for e in planted] + ["S0"]
    if trap == 4:
        now = world["patches"][1]
        return [e["content"] for e in planted] + [now[e["index"]]["content"] for e in planted]
    return [5]


def _wrong_values(world):
    p = world["passing"]
    base0 = world["patches"][0]
    planted_idx = {e["index"] for e in world["planted"]}
    others = [x for x in range(5) if x != p and x not in planted_idx]
    trap = world["trap"]
    if trap == 1:
        return [base0[p]["content"], base0[others[0]]["content"], "S0", 1]
    if trap == 2:
        return [2, 0, True, "1", base0[world["planted"][0]["index"]]["content"]]
    if trap == 3:
        return [base0[others[0]]["content"], base0[p]["content"], "S1", 3]
    if trap == 4:
        now = world["patches"][1]
        return [now[p]["content"], base0[others[0]]["content"], now[others[0]]["content"], "S1"]
    return [4, 1, base0[p]["content"]]


def _flags(length, at, flag, value):
    out = [[] for _ in range(length)]
    out[at] = [{flag: value}]
    return out


@pytest.mark.parametrize("w", PILOT_W)
@pytest.mark.parametrize("trap", TRAPS)
def test_each_naming_rule_fires_at_its_call_and_nowhere_else(trap, w):
    trapped, twin = _pair(trap, w)
    flag = tw.TRAP_FLAGS[trap]
    p = trapped["passing"]
    first = next(x for x in range(5) if x != p)
    record = _hand_run(trapped, [first, p])
    n = len(trapped["planted"])
    assert n == {1: 1, 2: 1, 3: 3, 4: 2, 5: 5}[trap]
    assert len(record) == n + 2 and record[-1]["verdict"] == "pass"
    L = len(record)

    for value in _right_values(trapped):
        right = _flags(L, n, flag, value)
        assert tw.named(trapped, record, right) is True
        assert tw.raised(trapped, record, right) is True
        assert tw.false_named(trapped, record, right) is False
        late = _flags(L, n + 1, flag, value)
        assert tw.named(trapped, record, late) is False
        assert tw.raised(trapped, record, late) is False
        early = _flags(L, n - 1, flag, value)
        assert tw.named(trapped, record, early) is False
        assert tw.raised(trapped, record, early) is False
        # The call one earlier reads a record one shorter, which no run makes.
        assert tw.named(trapped, record[: n - 1], _flags(n, n - 1, flag, value)) is not True

    for value in _wrong_values(trapped):
        wrong = _flags(L, n, flag, value)
        assert tw.named(trapped, record, wrong) is False
        assert tw.raised(trapped, record, wrong) is True

    other = "cycle" if flag != "cycle" else "repeat"
    assert tw.named(trapped, record, _flags(L, n, other, _right_values(trapped)[0])) is False
    assert tw.named(trapped, record, [[] for _ in range(L)]) is False
    assert tw.raised(trapped, record, [[] for _ in range(L)]) is False
    assert tw.named(trapped, record, [[] for _ in range(n)]) is None

    twin_record = _hand_run(twin, [first, p])
    m = len(twin["planted"])
    T = len(twin_record)
    for value in _right_values(trapped):
        for at in (m, m + 1):
            flags = _flags(T, at, flag, value)
            assert tw.named(twin, twin_record, flags) is not True
            assert tw.raised(twin, twin_record, flags) is False
            assert tw.false_named(twin, twin_record, flags) is True
    assert tw.false_named(twin, twin_record, _flags(T, m, flag, "anything")) is True
    assert tw.false_named(twin, twin_record, [[] for _ in range(T)]) is False
    assert tw.false_named(twin, twin_record, _flags(T, m, other, "anything")) is False


@pytest.mark.parametrize("trap", TRAPS)
def test_firing_counts_the_bait_and_the_same_choice_in_the_twin(trap):
    for w in PILOT_W:
        trapped, twin = _pair(trap, w)
        p = trapped["passing"]
        order = _draw(trap, w)["order"]
        bait = order[0] if trap != 5 else min(order)
        for world in (trapped, twin):
            assert tw.firing(world, _hand_run(world, [bait, p])) == [1]
            assert tw.firing(world, _hand_run(world, [p])) == []
            assert tw.firing(world, world["planted"]) == []
        if trap in (1, 2):
            for world in (trapped, twin):
                assert tw.firing(world, _hand_run(world, [order[1], order[2], bait, p])) == [3]
        if trap == 3:
            for world in (trapped, twin):
                assert tw.firing(world, _hand_run(world, [order[3], order[1], p])) == [2]
        if trap == 4:
            fresh = order[2]
            for world in (trapped, twin):
                assert tw.firing(world, _hand_run(world, [fresh, fresh, order[3], p])) == [2]
