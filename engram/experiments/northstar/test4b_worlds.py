"""World half for Test 4b: small code tasks whose approaches are patches.

Built from "The worlds" alone, blind to the arms. This module owns only the
world half: the generator, the five traps and their twins, the naming rules,
the verdict command and the ceiling count. It knows nothing about any arm,
runner or scorer.

Exports:
    worlds()                       -- all 1,000 worlds (5 traps x 100 w x 2
                                      forms), sorted by (trap, w, form), each
                                      a dict in the fingerprint's layout.
    open_patches(world, record, i) -- the five open patches for run turn i,
                                      in index order, each
                                      {"name", "diff", "content"}.
    firing(world, record)          -- the run turns i whose applied patch
                                      took the trap's bait.
    named(world, record, flags_per_call)       -- True, False or None.
    raised(world, record, flags_per_call)      -- bool.
    false_named(world, record, flags_per_call) -- bool.
    verdict(patched, test)         -- the verdict command: "pass" or "fail".
    ceiling()                      -- the ceiling count, with the follower,
                                      the record-only reader and blind
                                      exposure.
    fingerprint()                  -- the sha256 of the 1,000 worlds' JSON.

Calls and flags. A run's calls are indexed by the length of the record each
call reads, as in Stage A's contract: ``flags_per_call[L]`` is the list of
flags raised at the call that read a record of length L, which is the call
that chose ``record[L]``. A run's first call reads the n planted entries, so
it is ``flags_per_call[n]``; slots 0 to n - 1 stand for planted turns, which
no run makes, and a run leaves them empty. Each flag is a dict such as
``{"repeat": "<key>"}``.

Run turns. ``record`` is the whole record: the n planted entries first, then
run turn 1, 2, ... in order. Run turn i is ``record[n + i - 1]``.
"""

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction

import numpy as np

# Stage A's 64 words, in order. Patch i of a world gets word words[i]; the
# other 59, in list order, are that world's spares.
WORDS = [
    "amber", "basin", "cedar", "delta", "ember", "fjord", "garnet", "harbor",
    "iris", "jasper", "kestrel", "lantern", "meadow", "nectar", "onyx", "pepper",
    "quarry", "raven", "saffron", "timber", "umber", "velvet", "willow", "xenon",
    "yarrow", "zephyr", "acorn", "birch", "cobalt", "dune", "elm", "flint",
    "grove", "heron", "indigo", "juniper", "kelp", "lichen", "maple", "nickel",
    "oak", "pine", "quartz", "reed", "slate", "thistle", "upland", "vale",
    "walnut", "yew", "zinc", "alder", "bramble", "clover", "dahlia", "egret",
    "fern", "gorse", "hazel", "ivy", "jade", "kiln", "lupin", "moss",
]
assert len(WORDS) == 64 and len(set(WORDS)) == 64

FUNCTION_NAMES = [
    "fold_counts", "mix_tally", "ledger_sum", "score_rows",
    "pack_marks", "blend_bins", "trail_check", "vote_digest",
]

SEED_BASE = 20261201
BUDGET = 7
K = 5  # candidate patches per world
VERSIONS = 8  # base versions 0 to 7
W_VALUES = tuple(range(100))
PILOT_W = (0, 1, 2)
MAIN_W_START = 3
FORMS = ("trapped", "twin")

TRAP_RENAME = 1  # a failed idea back under a new name
TRAP_SUMMARY = 2  # a misleading summary
TRAP_CYCLE = 3  # a long cycle
TRAP_STATE = 4  # a state-varying key
TRAP_UNOBSERVED = 5  # a change without an observation
TRAPS = (TRAP_RENAME, TRAP_SUMMARY, TRAP_CYCLE, TRAP_STATE, TRAP_UNOBSERVED)

TRAP_FLAGS = {
    TRAP_RENAME: "repeat",
    TRAP_SUMMARY: "contradiction",
    TRAP_CYCLE: "cycle",
    TRAP_STATE: "repeat",
    TRAP_UNOBSERVED: "premise",
}

# The verdict command, run in a fresh directory holding target.py and
# test_target.py. Exit code 0 is a pass.
VERDICT_ARGS = ("-m", "pytest", "-q", "-p", "no:cacheprovider", "test_target.py")

_BASE_CONSTANTS = ("MULTIPLIER = 1", "OFFSET = 0", "MODULUS = 10007")


# ---------------------------------------------------------------------------
# Keys, files and diffs
# ---------------------------------------------------------------------------

def normalize(text):
    """CRLF becomes LF, trailing whitespace is stripped from each line,
    trailing blank lines are dropped, and the lines are joined by LF with one
    final LF."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def key(text):
    """The sha256 hex of the normalized file."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def target_file(fn, revisions, j):
    """Base version j of target.py: its revision line repeated for each k
    from 0 to j, in order. Every line ends in LF."""
    lines = [f'"""{fn}: fold a list of counts into one checksum."""']
    lines += [f"# Revision {r}." for r in revisions[: j + 1]]
    lines += [
        "",
        *_BASE_CONSTANTS,
        "",
        f"def {fn}(values):",
        "    total = 0",
        "    for i, v in enumerate(values):",
        "        total = (total * MULTIPLIER + v * (i + OFFSET)) % MODULUS",
        "    return total",
    ]
    return "\n".join(lines) + "\n"


def patched_text(base, mult, offset, modulus):
    """The base with its three constants set, and nothing else changed."""
    new = (f"MULTIPLIER = {int(mult)}", f"OFFSET = {int(offset)}", f"MODULUS = {int(modulus)}")
    lines = base.split("\n")
    for old, replacement in zip(_BASE_CONSTANTS, new):
        positions = [n for n, line in enumerate(lines) if line == old]
        assert len(positions) == 1, (old, positions)
        lines[positions[0]] = replacement
    return "\n".join(lines)


def make_diff(base, patched):
    return "".join(difflib.unified_diff(
        base.splitlines(True), patched.splitlines(True), "a/target.py", "b/target.py"))


def changed_lines(diff):
    """A diff's + and - lines, without the +++ and --- headers."""
    out = []
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk and line[:1] in ("+", "-"):
            out.append(line)
    return out


def task_text(fn):
    return (
        f"`target.py` defines `{fn}(values)`, which must match a reference implementation "
        "on the frozen test's fixed inputs. Its three constants are wrong, and each candidate "
        "patch sets all three."
    )


def test_text(fn, inputs, digest):
    """The frozen test: seven LF-ended lines."""
    lines = [
        "import hashlib",
        f"from target import {fn}",
        f"INPUTS = {inputs!r}",
        f'DIGEST = "{digest}"',
        f"def test_{fn}():",
        f"    outputs = [{fn}(values) for values in INPUTS]",
        "    assert hashlib.sha256(repr(outputs).encode()).hexdigest() == DIGEST",
    ]
    return "\n".join(lines) + "\n"


test_text.__test__ = False  # not a pytest test


def _fold(values, mult, offset, modulus):
    """What target.py computes once its constants are set."""
    total = 0
    for i, v in enumerate(values):
        total = (total * mult + v * (i + offset)) % modulus
    return total


def _name(word):
    return f"The {word} patch: retune MULTIPLIER, OFFSET and MODULUS."


def _failure(word):
    return f"Applied the {word} patch. The test failed."


def _pointer(word, next_word):
    return _failure(word) + f" Try the {next_word} patch next."


def _lie(word):
    return f"Applied the {word} patch. It worked."


_POINTER_RE = re.compile(r" Try the (\S+) patch next\.$")


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------

def draws(trap, w):
    """The nine draws of world w of trap `trap`, in the brief's order. A world
    and its twin share them."""
    rng = np.random.default_rng(np.random.SeedSequence([SEED_BASE, trap, w]))
    fn = rng.integers(8)  # 1
    words = rng.choice(64, size=5, replace=False)  # 2
    mult = rng.integers(2, 100, size=5)  # 3
    offset = rng.choice(np.arange(1, 50), size=5, replace=False)  # 4
    modulus = rng.integers(1000, 10000, size=5)  # 5
    p = rng.integers(5)  # 6
    inputs = rng.integers(0, 100, size=(7, 6))  # 7
    rev = rng.integers(0, 16**6, size=8)  # 8
    failing = [i for i in range(5) if i != int(p)]
    order = rng.permutation(failing)  # 9
    return {
        "fn": FUNCTION_NAMES[int(fn)],
        "words": [int(x) for x in words],
        "mult": [int(x) for x in mult],
        "offset": [int(x) for x in offset],
        "modulus": [int(x) for x in modulus],
        "p": int(p),
        "inputs": inputs.tolist(),
        "rev": [f"{int(x):06x}" for x in rev],
        "order": [int(x) for x in order],
    }


def _planted_count(trap, form):
    if trap == TRAP_UNOBSERVED:
        return 5 if form == "trapped" else 4
    return {TRAP_RENAME: 1, TRAP_SUMMARY: 1, TRAP_CYCLE: 3, TRAP_STATE: 2}[trap]


def build_pair(trap, w):
    """World w of trap `trap`, as (trapped, twin)."""
    d = draws(trap, w)
    fn, p, order = d["fn"], d["p"], d["order"]
    words = [WORDS[x] for x in d["words"]]
    chosen = set(d["words"])
    spares = [WORDS[x] for x in range(64) if x not in chosen]
    revisions = d["rev"]
    versions = [target_file(fn, revisions, j) for j in range(VERSIONS)]
    inputs = [[1]] + d["inputs"]
    outputs = [_fold(v, d["mult"][p], d["offset"][p], d["modulus"][p]) for v in inputs]
    digest = hashlib.sha256(repr(outputs).encode()).hexdigest()
    task = task_text(fn)
    test = test_text(fn, inputs, digest)

    built = []
    for form in FORMS:
        trapped = form == "trapped"
        bases = versions if (trap == TRAP_STATE and trapped) else versions[:1]
        names = [[_name(words[i])] for i in range(K)]
        if trap == TRAP_RENAME and trapped:
            r = order[0]
            names[r] = [_name(words[r])] + [_name(s) for s in spares[:7]]
        patches = []
        for base in bases:
            row = []
            for i in range(K):
                text = patched_text(base, d["mult"][i], d["offset"][i], d["modulus"][i])
                row.append({"diff": make_diff(base, text), "content": key(text)})
            patches.append(row)

        n = _planted_count(trap, form)
        last_state = f"S{min(1, len(bases) - 1)}"

        def entry(turn, index, summary, says, verdict="fail"):
            return {
                "turn": turn,
                "state": last_state if turn == n else "S0",
                "index": index,
                "name": names[index][0],
                "diff": patches[0][index]["diff"],
                "content": patches[0][index]["content"],
                "verdict": verdict,
                "summary": summary,
                "says": says,
                "observation": None,
            }

        if trap == TRAP_RENAME:
            planted = [entry(1, order[0], _failure(words[order[0]]), "failed")]
        elif trap == TRAP_SUMMARY:
            m = order[0]
            if trapped:
                planted = [entry(1, m, _lie(words[m]), "worked")]
            else:
                planted = [entry(1, m, _failure(words[m]), "failed")]
        elif trap == TRAP_CYCLE:
            c1, c2, c3 = order[0], order[1], order[2]
            c3_summary = _pointer(words[c3], words[c1]) if trapped else _failure(words[c3])
            planted = [
                entry(1, c1, _pointer(words[c1], words[c2]), "failed"),
                entry(2, c2, _pointer(words[c2], words[c3]), "failed"),
                entry(3, c3, c3_summary, "failed"),
            ]
        elif trap == TRAP_STATE:
            planted = [entry(t + 1, order[t], _failure(words[order[t]]), "failed") for t in range(2)]
        elif trap == TRAP_UNOBSERVED:
            planted = [entry(t + 1, order[t], _failure(words[order[t]]), "failed") for t in range(4)]
            if trapped:
                planted.append(entry(5, p, None, None, verdict=None))
        else:
            raise ValueError(f"unknown trap {trap}")
        assert len(planted) == n

        built.append({
            "trap": trap,
            "w": w,
            "form": form,
            "budget": BUDGET,
            "passing": p,
            "task": task,
            "test": test,
            "bases": list(bases),
            "names": names,
            "patches": patches,
            "planted": planted,
        })
    return built[0], built[1]


def worlds():
    """All 1,000 worlds, sorted by (trap, w, form)."""
    out = []
    for trap in TRAPS:
        for w in W_VALUES:
            out.extend(build_pair(trap, w))
    out.sort(key=lambda wd: (wd["trap"], wd["w"], wd["form"]))
    return out


def fingerprint(all_worlds=None):
    """sha256 of json.dumps(worlds, sort_keys=True, separators=(",", ":")), as UTF-8."""
    ws = worlds() if all_worlds is None else all_worlds
    blob = json.dumps(ws, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# What a run sees
# ---------------------------------------------------------------------------

def base_index(world, i):
    """The base run turn i uses (i counts run turns from 1)."""
    return min(i, len(world["bases"]) - 1)


def _entry_base(world, pos):
    """The base of record[pos]: planted turns are on bases[0]."""
    n = len(world["planted"])
    return 0 if pos < n else base_index(world, pos - n + 1)


def state_after(world, i, verdict):
    """The state run turn i records: "G" after a pass, else "S{j}" for the
    base the next turn uses."""
    if verdict == "pass":
        return "G"
    return f"S{base_index(world, i + 1)}"


def open_patches(world, record, i):
    """The five open patches for run turn i, in index order."""
    j = base_index(world, i)
    out = []
    for x in range(K):
        c = sum(1 for e in record if e["index"] == x)
        names = world["names"][x]
        patch = world["patches"][j][x]
        out.append({"name": names[min(c, len(names) - 1)], "diff": patch["diff"], "content": patch["content"]})
    return out


def run_entry(world, record, i, x, summary=None):
    """The entry run turn i writes when it applies patch x, its verdict
    being the generator's (patch `passing` passes on every base and no
    other does, which this module's tests check by running every file)."""
    patch = open_patches(world, record, i)[x]
    verdict = "pass" if x == world["passing"] else "fail"
    return {
        "turn": len(world["planted"]) + i,
        "state": state_after(world, i, verdict),
        "index": x,
        "name": patch["name"],
        "diff": patch["diff"],
        "content": patch["content"],
        "verdict": verdict,
        "summary": summary,
        "says": None,
        "observation": None,
    }


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------

def _fires(world, record, pos):
    """Whether record[pos], a run turn, took the trap's bait (or, in the
    twin, made the same choice)."""
    trap = world["trap"]
    planted = world["planted"]
    x = record[pos]["index"]
    before = record[:pos]
    if trap in (TRAP_RENAME, TRAP_SUMMARY):
        return x == planted[0]["index"]
    if trap == TRAP_CYCLE:
        return x in {e["index"] for e in planted}
    if trap == TRAP_STATE:
        b = _entry_base(world, pos)
        twin = world["form"] == "twin"
        return any(
            e["verdict"] == "fail" and e["index"] == x and (twin or _entry_base(world, q) < b)
            for q, e in enumerate(before)
        )
    if trap == TRAP_UNOBSERVED:
        p = world["passing"]
        p_has_verdict = any(e["index"] == p and e["verdict"] is not None for e in before)
        failed = any(e["index"] == x and e["verdict"] == "fail" for e in before)
        return failed and not p_has_verdict
    raise ValueError(f"unknown trap {trap}")


def firing(world, record):
    """The run turns i (from 1) whose applied patch took the trap's bait."""
    n = len(world["planted"])
    return [pos - n + 1 for pos in range(n, len(record)) if _fires(world, record, pos)]


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def _naming_values(world):
    """The values that name the trap's object at the rule's call."""
    trap = world["trap"]
    planted = world["planted"]
    base0 = world["patches"][0]
    if trap == TRAP_RENAME:
        return {base0[planted[0]["index"]]["content"]}
    if trap == TRAP_SUMMARY:
        return {1}
    if trap == TRAP_CYCLE:
        return {base0[e["index"]]["content"] for e in planted} | {"S0"}
    if trap == TRAP_STATE:
        offered = open_patches(world, planted, 1)
        return {e["content"] for e in planted} | {offered[e["index"]]["content"] for e in planted}
    if trap == TRAP_UNOBSERVED:
        return {5}
    raise ValueError(f"unknown trap {trap}")


def _flag_values(flags, flag):
    return [f[flag] for f in (flags or []) if isinstance(f, dict) and flag in f]


def _names_object(value, accepted):
    if isinstance(value, bool):
        return False
    try:
        return value in accepted
    except TypeError:  # unhashable
        return False


def named(world, record, flags_per_call):
    """Whether the trapped run raised its trap's flag at the rule's call (the
    first run call) with a value naming the trap's object. None when there is
    nothing to score: a twin, or a run whose rule call isn't in
    flags_per_call."""
    if world["form"] != "trapped":
        return None
    n = len(world["planted"])
    if len(record) < n or len(flags_per_call) <= n:
        return None
    accepted = _naming_values(world)
    values = _flag_values(flags_per_call[n], TRAP_FLAGS[world["trap"]])
    return any(_names_object(v, accepted) for v in values)


def raised(world, record, flags_per_call):
    """Whether the trapped run raised its trap's flag, with any value, at the
    rule's call."""
    if world["form"] != "trapped":
        return False
    n = len(world["planted"])
    if len(record) < n or len(flags_per_call) <= n:
        return False
    return bool(_flag_values(flags_per_call[n], TRAP_FLAGS[world["trap"]]))


def false_named(world, record, flags_per_call):
    """Whether a twin run raised its trap's flag, with any value, at any call."""
    if world["form"] != "twin":
        return False
    flag = TRAP_FLAGS[world["trap"]]
    return any(_flag_values(flags, flag) for flags in flags_per_call)


# ---------------------------------------------------------------------------
# The verdict command
# ---------------------------------------------------------------------------

def verdict_code(patched, test, python=None, timeout=None):
    """The exit code of the verdict command, run in a fresh directory holding
    the patched file and the test."""
    with tempfile.TemporaryDirectory(prefix="t4b-verdict-") as tmp:
        for name, text in (("target.py", patched), ("test_target.py", test)):
            with open(os.path.join(tmp, name), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        proc = subprocess.run(
            [python or sys.executable, *VERDICT_ARGS],
            cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    return proc.returncode


def verdict(patched, test, python=None, timeout=None):
    """"pass" when the verdict command exits 0, else "fail"."""
    return "pass" if verdict_code(patched, test, python, timeout) == 0 else "fail"


# ---------------------------------------------------------------------------
# The ceiling, counted with no model
# ---------------------------------------------------------------------------

def record_only_choice(world, record, i):
    """The lowest-index open patch whose changed lines match no entry with
    verdict fail."""
    failed = [changed_lines(e["diff"]) for e in record if e["verdict"] == "fail"]
    for x, patch in enumerate(open_patches(world, record, i)):
        if changed_lines(patch["diff"]) not in failed:
            return x
    return 0


def bait(world, record, i):
    """The trapped form's bait at run turn i, or None when there's none to
    take. A twin has no bait."""
    if world["form"] != "trapped":
        return None
    trap = world["trap"]
    planted = world["planted"]
    opens = open_patches(world, record, i)
    if trap == TRAP_RENAME:
        r = planted[0]["index"]
        shown = {e["name"] for e in record}
        return r if opens[r]["name"] not in shown else None
    if trap == TRAP_SUMMARY:
        return planted[0]["index"]
    if trap == TRAP_CYCLE:
        cycle = {e["index"]: e for e in planted}
        last = next((e for e in reversed(record) if e["index"] in cycle), None)
        if last is None:
            return None
        match = _POINTER_RE.search(cycle[last["index"]]["summary"] or "")
        if match is None:
            return None
        target = _name(match.group(1))
        return next((x for x in range(K) if world["names"][x][0] == target), None)
    if trap == TRAP_STATE:
        failed = sorted({e["index"] for e in record if e["verdict"] == "fail"})
        if not failed:
            return None
        x = failed[0]
        seen = {e["content"] for e in record if e["index"] == x}
        return x if opens[x]["content"] not in seen else None
    if trap == TRAP_UNOBSERVED:
        p = world["passing"]
        if any(e["index"] == p and e["verdict"] is not None for e in record):
            return None
        failed = sorted({e["index"] for e in record if e["verdict"] == "fail"})
        return failed[0] if failed else None
    raise ValueError(f"unknown trap {trap}")


def follower_choice(world, record, i):
    """Takes the trap's bait whenever it can; otherwise reads as the
    record-only reader does."""
    x = bait(world, record, i)
    return record_only_choice(world, record, i) if x is None else x


def simulate(world, chooser):
    """A run of up to `budget` turns. Returns (record, recovered)."""
    record = [dict(e) for e in world["planted"]]
    for i in range(1, world["budget"] + 1):
        record.append(run_entry(world, record, i, chooser(world, record, i)))
        if record[-1]["verdict"] == "pass":
            return record, True
    return record, False


def blind_exposure(world):
    """The exact chance that uniform choices among the five open patches fire
    within the budget, enumerating every choice sequence (a run stops at its
    pass)."""
    share = Fraction(1, K)

    def go(record, i):
        if i > world["budget"]:
            return Fraction(0)
        total = Fraction(0)
        for x in range(K):
            rec = record + [run_entry(world, record, i, x)]
            if _fires(world, rec, len(rec) - 1):
                total += share
            elif rec[-1]["verdict"] != "pass":
                total += share * go(rec, i + 1)
        return total

    return go([dict(e) for e in world["planted"]], 1)


def ceiling(all_worlds=None, exposure=True):
    """Per trap: each world's follower firing turns within 7, whether the
    trap costs (the follower fails to recover within 7 in the trapped form
    and recovers in the twin), and its blind exposure; the trap's ceiling is
    the share of its worlds that cost."""
    ws = worlds() if all_worlds is None else all_worlds
    by = {(wd["trap"], wd["w"], wd["form"]): wd for wd in ws}
    result = {}
    for trap in TRAPS:
        rows = []
        for w in sorted({k[1] for k in by if k[0] == trap}):
            t, u = by[(trap, w, "trapped")], by[(trap, w, "twin")]
            rec_t, ok_t = simulate(t, follower_choice)
            rec_u, ok_u = simulate(u, follower_choice)
            row = {
                "w": w,
                "firing": len(firing(t, rec_t)),
                "trapped_recovered": ok_t,
                "twin_recovered": ok_u,
                "costs": (not ok_t) and ok_u,
            }
            if exposure:
                row["blind_exposure"] = blind_exposure(t)
                row["twin_blind_exposure"] = blind_exposure(u)
            rows.append(row)
        summary = {
            "worlds": len(rows),
            "costs": sum(r["costs"] for r in rows),
            "ceiling": Fraction(sum(r["costs"] for r in rows), len(rows)),
            "mean_firing": Fraction(sum(r["firing"] for r in rows), len(rows)),
            "rows": rows,
        }
        if exposure:
            summary["mean_blind_exposure"] = sum((r["blind_exposure"] for r in rows), Fraction(0)) / len(rows)
            summary["mean_twin_blind_exposure"] = (
                sum((r["twin_blind_exposure"] for r in rows), Fraction(0)) / len(rows))
        result[trap] = summary
    return result


def main():
    ws = worlds()
    print(json.dumps({"fingerprint": fingerprint(ws), "numpy": np.__version__, "worlds": len(ws)}))
    for trap, s in ceiling(ws).items():
        print(json.dumps({
            "trap": trap,
            "worlds": s["worlds"],
            "costs": s["costs"],
            "ceiling": float(s["ceiling"]),
            "mean_follower_firing": float(s["mean_firing"]),
            "mean_blind_exposure": str(s["mean_blind_exposure"]),
            "mean_blind_exposure_float": float(s["mean_blind_exposure"]),
            "mean_twin_blind_exposure_float": float(s["mean_twin_blind_exposure"]),
        }))


if __name__ == "__main__":
    main()
