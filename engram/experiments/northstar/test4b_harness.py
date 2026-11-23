"""North-star test 4, stage B: the harness that joins the worlds and the arms.

Written by a third fresh agent from the approved spec
(docs/superpowers/specs/2026-11-23-north-star-test-4-stage-b-design.md, draft 5): "The arms", "The harness",
"What each arm sees", "Measures", "The size" and "The worlds", and from the visitor walk's frozen invocation
(docs/superpowers/specs/2026-11-23-visitor-first-hour-design.md, `tardis/visitor-walk-spec` 344e425a). It uses only
the halves' exports, never their bodies:

- worlds half (`test4b_worlds`): `worlds()`, `open_patches(world, record, i)`, `firing`, `named`, `raised`,
  `false_named`, the constant `VERDICT_ARGS` (the verdict command's arguments) and `PILOT_W`;
- arms half (`test4b_arms`): `prompt(arm, task, patches, record, keys=None, seed=0)`, `read_reply(text, k)`,
  `Malformed` and `ARMS`.

What it does:

- **A run** (`run`) is one world (which carries its trap, `w` and form), one arm, one repeat and one seed (the
  repeat's index unless given). Run turn `i` counts from 1, stalls included. Each turn's prompt comes from the arms'
  `prompt()` over the record so far and `open_patches(world, record, i)`, with the world's `name` given to the arms
  as `description`. R2 gets `keys`: one content key per record entry, the null-verdict entry included, then one per
  open patch. The turn is started through an injectable `call_turn(prompt_text) -> TurnResult`, and its reply read
  with `read_reply`.
- **Applying and testing** (`apply_and_test`): the chosen patch's diff is applied with `patch -p1` to a fresh copy of
  that turn's base, `bases[min(i, len(bases) - 1)]`; the patched file's normalized key must equal the key the world
  offered, or the harness stops. The verdict is the exit code of `python -m pytest -q -p no:cacheprovider
  test_target.py` (the world's `VERDICT_ARGS`), run in a second fresh directory holding only the patched file and
  the frozen test: 0 is "pass", 1 is "fail", and any other code stops the harness, since then pytest itself didn't
  run the test.
- **The run entry** (spec "The harness" (d)): `turn` is `n + i`, `state` is "G" after a pass or else
  `"S{min(i + 1, len(bases) - 1)}"`, `index`, `name` as offered, `diff` and `content` of the applied patch on that
  turn's base, `verdict`, the turn's own `summary`, `says` null and `observation` null.
- **Stalls** (c): a timeout (from `call_turn`) or a malformed reply (`Malformed`) is spent. It writes no entry and
  raises no flags, and `i` still counts it. `flags_per_call[L]` holds the (mapped) flags of the one read call that
  read a record of length L; slots 0 to n - 1 stay empty.
- **Faults** (c2): a faulted call is retried once after an injectable pause of 60 seconds. A second fault voids the
  run, which is rerun from its start with the same world, form, arm, repeat and seed. A fault and its retry are one
  run turn: `i` doesn't move on a fault.
- **The real call_turn** (`RealTurn`, `turn_argv`, `classify`): the frozen invocation, run under the systemd scope,
  bubblewrap and `env -i`, with stream-json parsed and classified. It is never run by the tests.
- **Scoring** (`score`): recovery; the six primary differences per trap, each the mean over worlds with a 95%
  percentile bootstrap CI over worlds; naming through `named` (traps 1, 2, 4 and 5) and `raised` (trap 3), with a
  `repeat` number mapped to that patch's key on `bases[0]` (its key as recorded) at the naming rule's call, while
  the logged flags keep the key at that call; false names in the twins; activity; firing turns; how many
  `contradiction` and `premise` values arrived as strings; stalls per arm and form, faults and reruns per arm;
  tokens and wall time beside them, never scored.
- **Arm order** (`arm_order`): within each world and repeat, the arms run in the order
  `numpy.random.default_rng([20261202, trap, w, repeat]).permutation(3)` over R0, R1, R2 (review advisory), so time
  effects don't fall on one arm. The report records every order.
- **A stopped series restarts whole.** When `MachineDown` (or any HarnessError) stops a series, it is run again from
  its first run, never resumed with chosen runs; nothing here resumes.
- **Size** (`pilot_size`): `N = ceil((2 * 1.96 * sigma / 0.30) ** 2)`, sigma the largest of the trap's six per-world
  standard deviations (ddof = 1), floored at 0.30.

Readings the spec left open are marked "Reading:" where they are made.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from experiments.northstar import test4b_arms as arms_half
from experiments.northstar import test4b_worlds as worlds_half

# ------------------------------------------------------------------ the spec's numbers

ARMS = ("R0", "R1", "R2")
EXPOSED_ARMS = ("R1", "R2")
FORMS = ("trapped", "twin")
TRAPS = (1, 2, 3, 4, 5)
RAISED_TRAPS = (3,)  # "Trap 3 is scored with raised, since a cycle note can't name a key."
PILOT_REPEATS = (0, 1, 2)

FAULT_PAUSE_SECONDS = 60
TURN_TIMEOUT_SECONDS = 120
# Reading: the spec gives no limit on reruns. A run that voids this many times in a row stops the series (raises
# MachineDown) instead of being dropped, since dropping it is what the rerun rule exists to prevent.
MAX_RERUNS = 3
VERDICT_TIMEOUT_SECONDS = 120

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261130
CI_LEVELS = (0.025, 0.975)

SIZE_Z = 1.96
SIZE_WIDTH = 0.30  # the CI's full width the formula aims at, so about +-0.15
SIGMA_FLOOR = 0.30
MAIN_RUN_CAP = 20
UNDERPOWERED_HALF_WIDTH = 0.15

# The six primary differences per trap ("Measures"): name -> (measure, arm a, arm b, expected sign).
# "fall_in" is on the trap effect (trapped recovery minus twin recovery, per world); "get_out" is on recovery in the
# trapped form. Each difference is arm a minus arm b.
PRIMARIES = (
    ("fall_in/R1-R0", "fall_in", "R1", "R0", "negative"),
    ("fall_in/R2-R0", "fall_in", "R2", "R0", "negative"),
    ("get_out/R1-R0", "get_out", "R1", "R0", "positive"),
    ("get_out/R2-R0", "get_out", "R2", "R0", "positive"),
    ("fall_in/R2-R1", "fall_in", "R2", "R1", None),
    ("get_out/R2-R1", "get_out", "R2", "R1", None),
)

ARM_ORDER_SEED = 20261202  # numpy.random.default_rng([20261202, trap, w, repeat]).permutation(3), over ARMS
STRING_TURN_FLAGS = ("contradiction", "premise")
RESTART_RULE = (
    "A series that MachineDown (or any HarnessError) stops is restarted whole, from its first run; it is never "
    "resumed, and no runs are chosen to keep."
)


class HarnessError(RuntimeError):
    """The harness or a half broke an invariant (a patch that won't apply, a key that doesn't match, a verdict
    command that didn't run). The series stops; nothing is recorded as data."""


class HarnessStop(HarnessError):
    """The machine isn't ready for a turn (a binary missing, an instruction file above the working directory, a
    sign-in file missing). The series stops before the call."""


class MachineDown(HarnessError):
    """A run voided more than MAX_RERUNS times in a row. The series stops rather than drop it.

    A series it stops restarts whole, from its first run, once the machine is fixed. It never resumes from where it
    stopped and never keeps chosen runs, so faults can't select which runs count. Nothing in this module resumes."""


# ------------------------------------------------------------------ what a call returns

TURN_KINDS = ("reply", "stall", "fault")


@dataclass(frozen=True)
class TurnResult:
    """One model call's outcome, as `call_turn` returns it.

    `kind` is "reply" (with the result event's text), "stall" (killed at the timeout with no api_retry event) or
    "fault" (c2). `reason` says why for a stall or a fault. `usage`, `seconds` and `transcript_sha256` are recorded,
    never scored."""

    kind: str
    text: str | None = None
    reason: str = ""
    usage: Mapping[str, float] = field(default_factory=dict)
    seconds: float = 0.0
    transcript_sha256: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in TURN_KINDS:
            raise ValueError(f"a turn result's kind is one of {TURN_KINDS}, not {self.kind!r}")

    @classmethod
    def reply(cls, text: str, **kw: Any) -> "TurnResult":
        return cls("reply", text=text, **kw)

    @classmethod
    def stall(cls, reason: str = "timeout", **kw: Any) -> "TurnResult":
        return cls("stall", reason=reason, **kw)

    @classmethod
    def fault(cls, reason: str, **kw: Any) -> "TurnResult":
        return cls("fault", reason=reason, **kw)


CallTurn = Callable[[str], TurnResult]
Verdict = Callable[..., tuple[str, str]]

# ------------------------------------------------------------------ content keys, applying, testing


def normalize(text: str) -> str:
    """The spec's normalization: CRLF becomes LF, trailing whitespace is stripped from each line, trailing blank lines
    are dropped, and the lines are joined by LF with one final LF."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def content_key(text: str) -> str:
    """The sha256 hex of the normalized file."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def base_for(world: Mapping, i: int) -> str:
    """The base run turn i uses: bases[min(i, len(bases) - 1)], i counting run turns from 1."""
    bases = world["bases"]
    return bases[min(i, len(bases) - 1)]


def state_after(world: Mapping, i: int, verdict: str) -> str:
    """The state run turn i records: "G" after a pass, else "S{j}" for the base the next turn uses."""
    if verdict == "pass":
        return "G"
    return f"S{min(i + 1, len(world['bases']) - 1)}"


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _verdict_env() -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for name in ("HOME", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def apply_and_test(
    base: str,
    diff: str,
    test: str,
    *,
    expect: str | None = None,
    python: str | None = None,
    timeout: float = VERDICT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Apply `diff` to a fresh copy of `base` with `patch -p1`, then run the frozen test on the result.

    Returns (patched file, verdict). `expect`, when given, is the content key the world offered for this patch on
    this base; a mismatch stops the harness. The verdict command runs in a second fresh directory holding only
    `target.py` and `test_target.py`."""
    with tempfile.TemporaryDirectory(prefix="t4b-apply-") as apply_dir:
        work = Path(apply_dir)
        _write(work / "target.py", base)
        applied = subprocess.run(
            ["patch", "-p1"], input=diff, cwd=work, capture_output=True, text=True, timeout=60, check=False
        )
        if applied.returncode != 0:
            raise HarnessError(f"patch -p1 failed ({applied.returncode}): {applied.stdout}{applied.stderr}")
        patched = _read(work / "target.py")
    if expect is not None and content_key(patched) != expect:
        raise HarnessError("the patched file's key isn't the key the world offered for this patch on this base")
    with tempfile.TemporaryDirectory(prefix="t4b-verdict-") as test_dir:
        here = Path(test_dir)
        _write(here / "target.py", patched)
        _write(here / "test_target.py", test)
        proc = subprocess.run(
            [python or sys.executable, *worlds_half.VERDICT_ARGS],
            cwd=here,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_verdict_env(),
            check=False,
        )
    if proc.returncode == 0:
        return patched, "pass"
    if proc.returncode == 1:
        return patched, "fail"
    # Reading: the spec says "0 is a pass". Pytest exits 1 when a test fails; 2 to 5 mean it never ran the test (an
    # interrupted collection, an internal or usage error, no tests). Counting those as "fail" would silently turn a
    # broken machine into non-recovery, so the harness stops instead.
    raise HarnessError(f"the verdict command exited {proc.returncode}: {proc.stdout[-500:]}{proc.stderr[-500:]}")


def check_verdict(world: Mapping, verdict: Verdict = apply_and_test) -> None:
    """Before a series: on the first run turn's base, the passing patch passes and one failing patch fails."""
    patches = worlds_half.open_patches(world, list(world["planted"]), 1)
    base = base_for(world, 1)
    passing = world["passing"]
    failing = next(x for x in range(len(patches)) if x != passing)
    if verdict(base, patches[passing]["diff"], world["test"], expect=patches[passing]["content"])[1] != "pass":
        raise HarnessStop("the verdict command doesn't pass the passing patch")
    if verdict(base, patches[failing]["diff"], world["test"], expect=patches[failing]["content"])[1] != "fail":
        raise HarnessStop("the verdict command doesn't fail a failing patch")


# ------------------------------------------------------------------ what the arms are given


def arm_patches(patches: Sequence[Mapping]) -> list[dict]:
    """Open patches as the arms take them: the world's `name` becomes `description`."""
    return [{"description": p["name"], "diff": p["diff"]} for p in patches]


def arm_record(record: Sequence[Mapping]) -> list[dict]:
    """Record entries as the arms take them. A null summary stays null; the arms render it."""
    return [
        {
            "turn": e["turn"],
            "description": e["name"],
            "diff": e["diff"],
            "verdict": e["verdict"],
            "summary": e["summary"],
        }
        for e in record
    ]


def r2_keys(record: Sequence[Mapping], patches: Sequence[Mapping]) -> list[str]:
    """(f): one key per record entry, the null-verdict entry included, then one per open patch."""
    return [e["content"] for e in record] + [p["content"] for p in patches]


def build_prompt(world: Mapping, arm: str, record: Sequence[Mapping], patches: Sequence[Mapping], seed: int) -> str:
    keys = r2_keys(record, patches) if arm == "R2" else None
    return arms_half.prompt(arm, world["task"], arm_patches(patches), arm_record(record), keys=keys, seed=seed)


# ------------------------------------------------------------------ naming


def patch_number(value: Any, k: int) -> int | None:
    """`repeat`'s value read as an open patch's number (W3): an integer from 0 to k - 1, or a string holding one.

    Reading: "a string holding one" is a string whose stripped text is all digits and whose value is in range, such
    as "3" or " 3 "; "patch 3" or 3.0 is not a number and stays as the turn wrote it. A bool is not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < k else None
    if isinstance(value, str):
        text = value.strip()
        if text.isascii() and text.isdigit():
            number = int(text)
            return number if 0 <= number < k else None
    return None


def map_flags(flags: Sequence[Mapping], patches: Sequence[Mapping]) -> list[dict]:
    """The flags of one read call, with each `repeat` number turned into that patch's key at that call.

    Reading: only `repeat` is mapped, as W3 says. Other flags' values pass through unchanged, so a `contradiction`
    or `premise` value is scored exactly as the turn wrote it."""
    out = []
    for flag in flags:
        ((name, value),) = flag.items()
        if name == "repeat":
            number = patch_number(value, len(patches))
            if number is not None:
                value = patches[number]["content"]
        out.append({name: value})
    return out


def scoring_flags(
    world: Mapping, flags_per_call: Sequence[Sequence[Mapping]], raw_flags_per_call: Sequence[Sequence[Mapping]]
) -> list[list[dict]]:
    """The flags `named`, `raised` and `false_named` are given (review: required change 1).

    At the naming rule's call, the first read call (slot n), a `repeat` number becomes that patch's key on
    `bases[0]`, its key "as recorded", which the rule accepts for traps 1 and 4 whatever `i` is. Mapping it to the
    key at that call instead fails trap 4 after a stalled first turn: that call's base is then `bases[2]` or later,
    while the rule accepts the key as recorded or as offered at i = 1. Every other slot is the logged flags, which
    keep the at-that-call mapping for the record. Traps 1, 2, 3 and 5 and every twin have one base, so there the two
    mappings agree."""
    n = len(world["planted"])
    out = [list(flags) for flags in flags_per_call]
    if len(out) > n:
        out[n] = map_flags(raw_flags_per_call[n], world["patches"][0])
    return out


# ------------------------------------------------------------------ one run


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _add_usage(total: dict[str, float], usage: Mapping[str, Any]) -> None:
    for name, value in usage.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[name] = total.get(name, 0) + value


def _call_log(outcome: TurnResult) -> dict:
    return {
        "kind": outcome.kind,
        "reason": outcome.reason,
        "seconds": outcome.seconds,
        "usage": dict(outcome.usage),
        "transcript_sha256": outcome.transcript_sha256,
    }


def _attempt(
    world: Mapping, arm: str, seed: int, call_turn: CallTurn, pause: Callable[[float], Any], verdict: Verdict
) -> dict:
    """One attempt at a run, from its start. Returns its record and logs, and whether it voided."""
    record = _json_copy(list(world["planted"]))
    n = len(record)
    flags_per_call: list[list[dict]] = [[] for _ in range(n)]
    raw_flags: list[list[dict]] = [[] for _ in range(n)]
    stalls: Counter[str] = Counter()
    stall_turns: list[int] = []
    faults = 0
    calls = 0
    usage: dict[str, float] = {}
    seconds = 0.0
    turn_log: list[dict] = []
    recovered_at: int | None = None
    turns = 0

    def call(text: str) -> TurnResult:
        nonlocal calls, faults, seconds
        outcome = call_turn(text)
        if not isinstance(outcome, TurnResult):
            raise HarnessError(f"call_turn returned {type(outcome).__name__}, not a TurnResult")
        calls += 1
        seconds += float(outcome.seconds or 0.0)
        _add_usage(usage, outcome.usage)
        if outcome.kind == "fault":
            faults += 1
        return outcome

    for i in range(1, int(world["budget"]) + 1):
        turns = i
        patches = worlds_half.open_patches(world, record, i)
        text = build_prompt(world, arm, record, patches, seed)
        log = {"i": i, "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "calls": []}
        turn_log.append(log)
        outcome = call(text)
        log["calls"].append(_call_log(outcome))
        if outcome.kind == "fault":
            pause(FAULT_PAUSE_SECONDS)
            outcome = call(text)
            log["calls"].append(_call_log(outcome))
            if outcome.kind == "fault":
                log["result"] = "void"
                return {
                    "void": True,
                    "void_at": i,
                    "turns": turns,
                    "calls": calls,
                    "faults": faults,
                    "stalls": dict(stalls),
                    "usage": usage,
                    "seconds": seconds,
                    "turn_log": turn_log,
                }
        if outcome.kind == "stall":
            reason = outcome.reason or "timeout"
            stalls[reason] += 1
            stall_turns.append(i)
            log.update(result="stall", stall=reason)
            continue
        try:
            text_back = outcome.text if outcome.text is not None else ""
            choice, summary, flags = arms_half.read_reply(text_back, len(patches))
        except arms_half.Malformed as exc:
            stalls["malformed"] += 1
            stall_turns.append(i)
            log.update(result="stall", stall="malformed", malformed=str(exc))
            continue
        chosen = patches[choice]
        _patched, result = verdict(base_for(world, i), chosen["diff"], world["test"], expect=chosen["content"])
        entry = {
            "turn": n + i,
            "state": state_after(world, i, result),
            "index": choice,
            "name": chosen["name"],
            "diff": chosen["diff"],
            "content": chosen["content"],
            "verdict": result,
            "summary": summary,
            "says": None,
            "observation": None,
        }
        record.append(entry)
        raw_flags.append(_json_copy(list(flags)))
        flags_per_call.append(map_flags(flags, patches))
        log.update(result="entry", choice=choice, verdict=result)
        if result == "pass":
            recovered_at = i
            break
    return {
        "void": False,
        "turns": turns,
        "calls": calls,
        "faults": faults,
        "stalls": dict(stalls),
        "stall_turns": stall_turns,
        "usage": usage,
        "seconds": seconds,
        "turn_log": turn_log,
        "record": record,
        "flags_per_call": flags_per_call,
        "raw_flags_per_call": raw_flags,
        "recovered_at": recovered_at,
    }


def firing_turns(world: Mapping, record: Sequence[Mapping]) -> list[int]:
    """The run turns i whose applied patch took the bait, i counting stalls.

    The worlds half numbers a run's entries by position ("Run turn i is record[n + i - 1]"), which matches i only
    when no turn stalled. So each position it returns is mapped back to its entry's own turn, minus n."""
    n = len(world["planted"])
    run_entries = record[n:]
    out = []
    for position in worlds_half.firing(world, list(record)):
        position = int(position)
        if not 1 <= position <= len(run_entries):
            raise HarnessError(f"firing returned run turn {position}, but the run wrote {len(run_entries)} entries")
        out.append(int(run_entries[position - 1]["turn"]) - n)
    return out


def run(
    world: Mapping,
    arm: str,
    repeat: int,
    *,
    call_turn: CallTurn,
    seed: int | None = None,
    pause: Callable[[float], Any] = time.sleep,
    verdict: Verdict = apply_and_test,
    max_reruns: int = MAX_RERUNS,
) -> dict:
    """One run: a world (in one form), an arm, a repeat and a seed (the repeat's index unless given).

    A void attempt is rerun from its start with the same inputs; the result is the first attempt that didn't void,
    with every voided attempt summarised beside it."""
    if arm not in ARMS:
        raise ValueError(f"arm is one of {ARMS}, not {arm!r}")
    seed = int(repeat if seed is None else seed)
    voided: list[dict] = []
    faults = 0
    calls = 0
    usage: dict[str, float] = {}
    seconds = 0.0
    while True:
        attempt = _attempt(world, arm, seed, call_turn, pause, verdict)
        faults += attempt["faults"]
        calls += attempt["calls"]
        _add_usage(usage, attempt["usage"])
        seconds += attempt["seconds"]
        if not attempt["void"]:
            break
        voided.append({k: attempt[k] for k in ("void_at", "turns", "calls", "faults", "stalls", "turn_log")})
        if len(voided) > max_reruns:
            raise MachineDown(
                f"trap {world['trap']} w {world['w']} {world['form']} {arm} repeat {repeat}: "
                f"voided {len(voided)} times in a row"
            )
    record = attempt["record"]
    flags_per_call = attempt["flags_per_call"]
    n = len(world["planted"])
    read_any = len(flags_per_call) > n
    scoring = scoring_flags(world, flags_per_call, attempt["raw_flags_per_call"])
    named = raised = None
    false_named = None
    if world["form"] == "trapped":
        if read_any:
            named = worlds_half.named(world, record, scoring)
            raised = bool(worlds_half.raised(world, record, scoring))
    else:
        false_named = bool(worlds_half.false_named(world, record, scoring))
    run_entries = record[n:]
    return {
        "trap": int(world["trap"]),
        "w": int(world["w"]),
        "form": world["form"],
        "arm": arm,
        "repeat": int(repeat),
        "seed": seed,
        "recovered": attempt["recovered_at"] is not None,
        "recovered_at": attempt["recovered_at"],
        "turns": attempt["turns"],
        "entries": len(run_entries),
        "stalls": attempt["stalls"],
        "stall_turns": attempt["stall_turns"],
        "faults": faults,
        "reruns": len(voided),
        "voided": voided,
        "calls": calls,
        "usage": usage,
        "seconds": seconds,
        "record": record,
        "flags_per_call": flags_per_call,
        "scoring_flags_per_call": scoring,
        "raw_flags_per_call": attempt["raw_flags_per_call"],
        "firing": firing_turns(world, record),
        "named": None if named is None else bool(named),
        "raised": raised,
        "false_named": false_named,
        "distinct_indices": len({e["index"] for e in run_entries}),
        "turn_log": attempt["turn_log"],
    }


# ------------------------------------------------------------------ series and the pilot


def select_worlds(
    all_worlds: Sequence[Mapping] | None = None,
    traps: Iterable[int] = TRAPS,
    ws: Iterable[int] = worlds_half.PILOT_W,
    forms: Iterable[str] = FORMS,
) -> list[Mapping]:
    """The worlds of the given traps, `w` values and forms, sorted by (trap, w, form)."""
    pool = worlds_half.worlds() if all_worlds is None else all_worlds
    traps, ws, forms = set(traps), set(ws), set(forms)
    chosen = [w for w in pool if w["trap"] in traps and w["w"] in ws and w["form"] in forms]
    return sorted(chosen, key=lambda w: (w["trap"], w["w"], w["form"]))


def run_series(
    worlds: Sequence[Mapping],
    *,
    call_turn: CallTurn,
    arms: Sequence[str] = ARMS,
    repeats: Sequence[int] = PILOT_REPEATS,
    pause: Callable[[float], Any] = time.sleep,
    verdict: Verdict = apply_and_test,
    max_reruns: int = MAX_RERUNS,
    on_run: Callable[[dict], Any] | None = None,
) -> list[dict]:
    """Every run of `worlds` x `arms` x `repeats`, from the first, in one pass. The verdict command is checked once
    first.

    The order is repeat, then world (by trap, w, form), then the arms in `arm_order(trap, w, repeat)`, so both forms
    of a world share an order within a repeat and drift over a long series doesn't fall on one arm. Each run records
    its `arm_order` and its `position` in the series. `on_run` is for logging as runs finish; a series that stops is
    restarted whole (RESTART_RULE), never resumed from what `on_run` saved."""
    if not worlds:
        return []
    check_verdict(worlds[0], verdict)
    runs = []
    for repeat in repeats:
        for world in worlds:
            order = [arm for arm in arm_order(world["trap"], world["w"], repeat) if arm in arms]
            for arm in order:
                result = run(
                    world, arm, repeat, call_turn=call_turn, pause=pause, verdict=verdict, max_reruns=max_reruns
                )
                result["arm_order"] = order
                result["position"] = len(runs)
                runs.append(result)
                if on_run is not None:
                    on_run(result)
    return runs


def arm_order(trap: int, w: int, repeat: int) -> list[str]:
    """The arms' order within world (trap, w) at this repeat (review advisory)."""
    permutation = np.random.default_rng([ARM_ORDER_SEED, int(trap), int(w), int(repeat)]).permutation(len(ARMS))
    return [ARMS[int(k)] for k in permutation]


def pilot(call_turn: CallTurn, **kw: Any) -> dict:
    """The pilot: w 0 to 2 per trap, both forms, all three arms, 3 repeats (270 runs), scored."""
    runs = run_series(select_worlds(), call_turn=call_turn, repeats=PILOT_REPEATS, **kw)
    return {"runs": runs, "report": score(runs)}


# ------------------------------------------------------------------ scoring


def resample_matrix(world_count: int) -> np.ndarray:
    """One trap's resample matrix of world indices, from a fresh generator, as stage A has it."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    return rng.integers(0, world_count, size=(BOOTSTRAP_RESAMPLES, world_count))


def bootstrap_ci(values: Sequence[float], matrix: np.ndarray) -> tuple[float, float, float]:
    """The mean over worlds and its 95% percentile bootstrap CI over `matrix`'s resamples."""
    values = np.asarray(values, dtype=float)
    means = values[matrix].mean(axis=1)
    low, high = np.quantile(means, CI_LEVELS)
    return float(values.mean()), float(low), float(high)


def pilot_size(sigma_raw: float | None) -> dict:
    """The main run's worlds per trap from the pilot's sigma: N = ceil((2 * 1.96 * sigma / 0.30) ** 2), with sigma
    floored at 0.30. The main run takes min(N, 20).

    Reading: with fewer than two pilot worlds there is no ddof = 1 deviation, so sigma_raw is None and N is None."""
    if sigma_raw is None or not math.isfinite(sigma_raw):
        return {"sigma_raw": None, "sigma": None, "N": None, "worlds_to_run": None, "passes_20": None}
    sigma = max(float(sigma_raw), SIGMA_FLOOR)
    n_worlds = math.ceil((2 * SIZE_Z * sigma / SIZE_WIDTH) ** 2)
    return {
        "sigma_raw": float(sigma_raw),
        "sigma": sigma,
        "N": n_worlds,
        "worlds_to_run": min(n_worlds, MAIN_RUN_CAP),
        "passes_20": n_worlds > MAIN_RUN_CAP,
    }


def _mean(values: Sequence[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _recovery_cells(runs: Sequence[Mapping], trap: int) -> tuple[list[int], dict]:
    """Per world, arm and form: the recovery rate over the world's repeats. Every world must have every cell, over
    the same repeats."""
    cells: dict[tuple[int, str, str], dict[int, bool]] = {}
    for r in runs:
        if r["trap"] != trap:
            continue
        cell = cells.setdefault((r["w"], r["arm"], r["form"]), {})
        if r["repeat"] in cell:
            raise HarnessError(f"two runs of trap {trap} w {r['w']} {r['arm']} {r['form']} repeat {r['repeat']}")
        cell[r["repeat"]] = bool(r["recovered"])
    ws = sorted({w for (w, _, _) in cells})
    rates: dict[tuple[int, str, str], float] = {}
    for w in ws:
        repeats = None
        for arm in ARMS:
            for form in FORMS:
                cell = cells.get((w, arm, form))
                if not cell:
                    raise HarnessError(f"trap {trap} w {w} has no {arm} {form} runs")
                if repeats is None:
                    repeats = set(cell)
                elif set(cell) != repeats:
                    raise HarnessError(f"trap {trap} w {w}: {arm} {form} has repeats {sorted(cell)}")
                rates[(w, arm, form)] = sum(cell.values()) / len(cell)
    return ws, rates


def primaries(ws: Sequence[int], rates: Mapping[tuple[int, str, str], float]) -> dict:
    """The six primary differences for one trap: per world, then the mean and its bootstrap CI over worlds. One
    resample matrix per trap, from a fresh generator, shared by all six (as stage A shares one per trap)."""

    def effect(w: int, arm: str) -> float:
        return rates[(w, arm, "trapped")] - rates[(w, arm, "twin")]

    def measure(kind: str, w: int, arm: str) -> float:
        return effect(w, arm) if kind == "fall_in" else rates[(w, arm, "trapped")]

    matrix = resample_matrix(len(ws))
    out = {}
    for name, kind, a, b, sign in PRIMARIES:
        per_world = [measure(kind, w, a) - measure(kind, w, b) for w in ws]
        mean, low, high = bootstrap_ci(per_world, matrix)
        sd = float(np.std(per_world, ddof=1)) if len(per_world) > 1 else None
        half = (high - low) / 2
        out[name] = {
            "measure": kind,
            "a": a,
            "b": b,
            "expected_sign": sign,
            "per_world": {int(w): float(v) for w, v in zip(ws, per_world)},
            "mean": mean,
            "ci": [low, high],
            "half_width": half,
            "wider_than_0.15": bool(half > UNDERPOWERED_HALF_WIDTH),
            "excludes_zero": bool(low > 0 or high < 0),
            "sd": sd,
        }
    return out


def _naming(trap_runs: Sequence[Mapping], trap: int) -> dict:
    rule = "raised" if trap in RAISED_TRAPS else "named"
    out: dict[str, Any] = {"rule": rule, "arms": {}}
    for arm in EXPOSED_ARMS:
        trapped = [r for r in trap_runs if r["arm"] == arm and r["form"] == "trapped"]
        answers = [r[rule] for r in trapped]
        scored = [a for a in answers if a is not None]
        hits = sum(1 for a in scored if a)
        raised = [r["raised"] for r in trapped if r["raised"] is not None]
        out["arms"][arm] = {
            "trapped_runs": len(trapped),
            "scored": len(scored),
            "unscored": len(answers) - len(scored),
            "named": hits,
            "rate": hits / len(scored) if scored else None,
            "raised": sum(1 for a in raised if a),
        }
    return out


def _false_names(trap_runs: Sequence[Mapping]) -> dict:
    out = {}
    for arm in ARMS:
        twins = [r for r in trap_runs if r["arm"] == arm and r["form"] == "twin"]
        count = sum(1 for r in twins if r["false_named"])
        out[arm] = {"twin_runs": len(twins), "false_names": count, "rate": count / len(twins) if twins else None}
    return out


def _by_arm_form(trap_runs: Sequence[Mapping], fn: Callable[[list[Mapping]], dict]) -> dict:
    return {
        arm: {form: fn([r for r in trap_runs if r["arm"] == arm and r["form"] == form]) for form in FORMS}
        for arm in ARMS
    }


def _activity(cell: list[Mapping]) -> dict:
    """Distinct patch indices tried, in runs that don't recover. Reported, never scored."""
    unrecovered = [r for r in cell if not r["recovered"]]
    return {"runs": len(unrecovered), "mean_distinct_indices": _mean([r["distinct_indices"] for r in unrecovered])}


def _firing(cell: list[Mapping]) -> dict:
    return {
        "runs": len(cell),
        "mean_firing_turns": _mean([len(r["firing"]) for r in cell]),
        "runs_firing": sum(1 for r in cell if r["firing"]),
    }


def _recovery(cell: list[Mapping]) -> dict:
    return {"runs": len(cell), "recovered": sum(1 for r in cell if r["recovered"]),
            "rate": _mean([1.0 if r["recovered"] else 0.0 for r in cell])}


def _stall_counts(runs: Sequence[Mapping]) -> dict:
    """Stalls in the counted attempts (by reason), stalls inside voided attempts, faults and reruns."""
    stalls: Counter[str] = Counter()
    voided_stalls = 0
    for r in runs:
        stalls.update(r["stalls"])
        voided_stalls += sum(sum(v["stalls"].values()) for v in r.get("voided", ()))
    return {
        "runs": len(runs),
        "stalls": sum(stalls.values()),
        "stalls_by_reason": dict(sorted(stalls.items())),
        "stalls_in_voided_attempts": voided_stalls,
        "faults": sum(r["faults"] for r in runs),
        "reruns": sum(r["reruns"] for r in runs),
    }


def string_turn_values(runs: Sequence[Mapping]) -> dict[str, int]:
    """How many `contradiction` and `premise` values arrived as strings (review advisory), over every read call of
    the counted attempts. The worlds' `named` takes only an integer turn, so these score as not named."""
    counts = {name: 0 for name in STRING_TURN_FLAGS}
    for r in runs:
        for flags in r.get("raw_flags_per_call", ()):
            for flag in flags:
                for name, value in flag.items():
                    if name in counts and isinstance(value, str):
                        counts[name] += 1
    return counts


def _per_arm(runs: Sequence[Mapping]) -> dict:
    out = {}
    for arm in ARMS:
        mine = [r for r in runs if r["arm"] == arm]
        usage: dict[str, float] = {}
        for r in mine:
            _add_usage(usage, r["usage"])
        turns = sum(r["turns"] for r in mine)
        calls = sum(r["calls"] for r in mine)
        seconds = sum(r["seconds"] for r in mine)
        out[arm] = {
            **_stall_counts(mine),
            "turns": turns,  # run turns of the counted attempts; `calls` holds every model call, voids included
            "calls": calls,
            "by_form": {form: _stall_counts([r for r in mine if r["form"] == form]) for form in FORMS},
            "string_turn_values": string_turn_values(mine),
            "usage": usage,
            "seconds": seconds,
            "seconds_per_call": seconds / calls if calls else None,
        }
    return out


def _arm_orders(runs: Sequence[Mapping]) -> list[dict]:
    """Each (trap, w, repeat)'s arm order, as the series ran it."""
    orders: dict[tuple[int, int, int], list[str]] = {}
    for r in runs:
        if "arm_order" in r:
            orders.setdefault((r["trap"], r["w"], r["repeat"]), list(r["arm_order"]))
    return [{"trap": t, "w": w, "repeat": rep, "order": order} for (t, w, rep), order in sorted(orders.items())]


def score(runs: Sequence[Mapping]) -> dict:
    """The report: per trap, never pooled, the six primaries with their CIs, recovery, naming beside them, false
    names, string-valued turn numbers, activity, firing and the pilot's size; per arm, stalls (also per form),
    faults, reruns, tokens and wall time; the arm orders run, and the restart rule."""
    traps = {}
    for trap in sorted({r["trap"] for r in runs}):
        trap_runs = [r for r in runs if r["trap"] == trap]
        ws, rates = _recovery_cells(runs, trap)
        prim = primaries(ws, rates)
        sds = [p["sd"] for p in prim.values()]
        sigma_raw = max(sds) if all(sd is not None for sd in sds) else None
        traps[trap] = {
            "worlds": [int(w) for w in ws],
            "recovery": _by_arm_form(trap_runs, _recovery),
            "recovery_per_world": {
                arm: {form: {int(w): rates[(w, arm, form)] for w in ws} for form in FORMS} for arm in ARMS
            },
            "primaries": prim,
            "underpowered": any(p["wider_than_0.15"] for p in prim.values()),
            "naming": _naming(trap_runs, trap),
            "false_names": _false_names(trap_runs),
            "string_turn_values": {arm: string_turn_values([r for r in trap_runs if r["arm"] == arm]) for arm in ARMS},
            "activity": _by_arm_form(trap_runs, _activity),
            "firing": _by_arm_form(trap_runs, _firing),
            "size": pilot_size(sigma_raw),
        }
    return {
        "runs": len(runs),
        "traps": traps,
        "per_arm": _per_arm(runs),
        "string_turn_values": string_turn_values(runs),
        "arm_orders": _arm_orders(runs),
        "arm_order_rule": (
            f"numpy.random.default_rng([{ARM_ORDER_SEED}, trap, w, repeat]).permutation(3) over R0, R1, R2"
        ),
        "restart_rule": RESTART_RULE,
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "rng": f"numpy.random.default_rng({BOOTSTRAP_SEED}), fresh per trap, one matrix shared by its six",
            "quantiles": list(CI_LEVELS),
            "method": "numpy.quantile default (linear)",
        },
        "size_rule": "N = ceil((2 * 1.96 * sigma / 0.30) ** 2), sigma = max over six per-world sd (ddof 1), floor 0.30",
    }


def provenance() -> dict:
    """The three modules' sha256, the worlds' fingerprint and numpy's version, for posting with a result."""

    def sha(module: Any) -> str:
        return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()

    return {
        "test4b_worlds.py": sha(worlds_half),
        "test4b_arms.py": sha(arms_half),
        "test4b_harness.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fingerprint": worlds_half.fingerprint(),
        "numpy": np.__version__,
    }


# ------------------------------------------------------------------ the real call_turn (never run by the tests)


@dataclass(frozen=True)
class Wrapper:
    """The visitor walk's frozen wrapper, with the turn's paths. (b): one working directory for every turn, with
    home/ and uv-cache/ outside it. (g): the turns' own sign-in directory.

    Reading: the spec names no path for the turns' sign-in directory; it is /var/tmp/t4b-config, the walk's
    pattern."""

    claude: str = "/home/doctor/.local/share/claude/versions/2.1.330"
    uv: str = "/home/doctor/.local/bin/uv"
    uvx: str = "/home/doctor/.local/bin/uvx"
    account_home: str = "/home/doctor"
    turn_dir: str = "/var/tmp/t4b-turn"
    home_dir: str = "/var/tmp/t4b-home"
    config_dir: str = "/var/tmp/t4b-config"
    model: str = "claude-sonnet-5-5"
    timeout: int = TURN_TIMEOUT_SECONDS
    path: str = "/home/doctor/.local/bin:/usr/local/bin:/usr/bin:/bin"


FROZEN = Wrapper()
EMPTY_MCP_CONFIG = '{"mcpServers":{}}'


def turn_argv(prompt_text: str, *, unit: str, wrapper: Wrapper = FROZEN) -> list[str]:
    """The frozen invocation for one turn: systemd scope, `timeout 120`, bubblewrap with the account's home hidden
    and `--unshare-pid`, `env -i`, then `claude -p` with no tools, an empty MCP config, Sonnet 5.5 and stream-json.
    No `--allowedTools` and no permission mode."""
    w = wrapper
    return [
        "systemd-run", "--user", "--scope", f"--unit={unit}", "--",
        "timeout", str(w.timeout),
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--tmpfs", "/tmp", "--tmpfs", "/var/tmp", "--tmpfs", w.account_home,
        "--ro-bind", w.claude, w.claude, "--ro-bind", w.uv, w.uv, "--ro-bind", w.uvx, w.uvx,
        "--bind", w.turn_dir, w.turn_dir, "--bind", w.home_dir, w.home_dir, "--bind", w.config_dir, w.config_dir,
        "--chdir", w.turn_dir, "--die-with-parent", "--unshare-pid", "--",
        "env", "-i", f"PATH={w.path}", "LANG=C.UTF-8", "TERM=dumb", "TZ=UTC",
        f"HOME={w.home_dir}/home", f"UV_CACHE_DIR={w.home_dir}/uv-cache", f"CLAUDE_CONFIG_DIR={w.config_dir}",
        "GIT_SSH_COMMAND=false",
        w.claude, "-p", prompt_text, "--model", w.model, "--output-format", "stream-json", "--verbose",
        "--tools", "", "--strict-mcp-config", "--mcp-config", EMPTY_MCP_CONFIG,
    ]  # fmt: skip


def _events(stream: str) -> tuple[list[dict], int]:
    events, junk = [], 0
    for line in stream.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            junk += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            junk += 1
    return events, junk


def _result_usage(result: Mapping) -> dict[str, float]:
    usage: dict[str, float] = {}
    for name, value in (result.get("usage") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[name] = value
    for name in ("total_cost_usd", "duration_ms", "duration_api_ms", "num_turns"):
        value = result.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage[name] = value
    return usage


def classify(
    stream: str,
    *,
    killed: bool,
    seconds: float = 0.0,
    transcript_sha256: str | None = None,
    returncode: int | None = None,
) -> TurnResult:
    """One call's stream-json, read by (a), (c) and (c2).

    - Any init event listing tools or MCP servers is a fault (an init event missing either list counts as listing
      something, since the check can't pass).
    - A result event with `is_error` true is a fault.
    - A result event otherwise is the reply: its `result` text. Reading: a result with no init event before it is a
      fault, since the check that must hold on every turn wasn't made.
    - No result, killed at the timeout: a fault after any `system`/`api_retry` event, else a stall.
    - No result, exited on its own before the kill: a fault.
    """
    events, junk = _events(stream)
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    retries = [e for e in events if e.get("type") == "system" and e.get("subtype") == "api_retry"]
    results = [e for e in events if e.get("type") == "result"]
    meta = {
        "events": len(events),
        "junk_lines": junk,
        "api_retries": len(retries),
        "model": inits[0].get("model") if inits else None,
        "killed": killed,
        "returncode": returncode,
    }
    usage = _result_usage(results[-1]) if results else {}
    common = {"usage": usage, "seconds": seconds, "transcript_sha256": transcript_sha256, "meta": meta}
    for init in inits:
        tools, servers = init.get("tools"), init.get("mcp_servers")
        if not isinstance(tools, list) or not isinstance(servers, list):
            return TurnResult.fault("init event lacks its tools or MCP server list", **common)
        if tools:
            return TurnResult.fault(f"init lists tools: {tools!r}", **common)
        if servers:
            return TurnResult.fault(f"init lists MCP servers: {servers!r}", **common)
    if results:
        result = results[-1]
        if result.get("is_error"):
            return TurnResult.fault(f"result is_error ({result.get('subtype')})", **common)
        if not inits:
            return TurnResult.fault("a result with no init event", **common)
        text = result.get("result")
        return TurnResult.reply(text if isinstance(text, str) else "", **common)
    if killed:
        if retries:
            return TurnResult.fault("killed at the timeout after an api_retry event", **common)
        return TurnResult.stall("timeout", **common)
    return TurnResult.fault("exited with no result", **common)


def read_signin_list(path: str | os.PathLike) -> frozenset[str]:
    """The sign-in's files, listed once at sign-in: one path per line, relative to the config directory."""
    names = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return frozenset(name for name in names if name and not name.startswith("#"))


def reset_config(config_dir: str | os.PathLike, signin_files: Iterable[str]) -> list[str]:
    """(g): delete everything in the config directory but the sign-in's files. Returns what it deleted.

    A listed file that is missing stops the harness: the sign-in is broken, and a turn would fault."""
    root = Path(config_dir)
    keep = {Path(name) for name in signin_files}
    if not keep:
        raise HarnessStop("no sign-in files listed")
    for name in keep:
        if name.is_absolute() or ".." in name.parts:
            raise HarnessStop(f"a sign-in file must be relative and inside the directory: {name}")
        if not (root / name).is_file():
            raise HarnessStop(f"the sign-in file {name} is missing")
    keep_dirs = {parent for name in keep for parent in name.parents if parent != Path(".")}
    deleted = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(root)
        if rel in keep or rel in keep_dirs:
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            if any(path.iterdir()):
                continue  # holds a kept file deeper down; its other contents went first
            path.rmdir()
        else:
            path.unlink()
        deleted.append(str(rel))
    return deleted


def _fresh_dir(path: str | os.PathLike) -> None:
    """Remove and recreate a directory under /var/tmp, mode 0700, refusing a symlink or another owner's directory.
    The path must be absolute and resolve to a direct child of /var/tmp, never /var/tmp itself (Rio Grande's read,
    ee19164a), so no Walker built with another path can clear it."""
    target = Path(path)
    # The resolved parent is compared with the resolved base, since on macOS /var is a link to /private/var
    # (Rio Grande's read, c21d7d83).
    if not target.is_absolute() or Path(os.path.realpath(target)).parent != Path(os.path.realpath("/var/tmp")) \
            or Path(os.path.normpath(target)).parent != Path("/var/tmp"):
        raise HarnessStop(f"{target} isn't a direct child of /var/tmp")
    if target.is_symlink():
        raise HarnessStop(f"{target} is a symlink")
    if target.exists():
        if target.stat().st_uid != os.getuid():
            raise HarnessStop(f"{target} belongs to another account")
        shutil.rmtree(target)
    target.mkdir(mode=0o700)
    info = target.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise HarnessStop(f"{target} isn't this account's new directory")


INSTRUCTION_NAMES = ("CLAUDE.md", "CLAUDE.local.md", ".claude")


def check_no_instructions(dirs: Iterable[str] = ("/var/tmp", "/var", "/"), policy: str = "/etc/claude-code") -> None:
    """The walk's check (Z2): no CLAUDE.md, CLAUDE.local.md or .claude/ above the working directory, and no managed
    policy directory."""
    for directory in dirs:
        for name in INSTRUCTION_NAMES:
            if os.path.lexists(os.path.join(directory, name)):
                raise HarnessStop(f"{os.path.join(directory, name)} exists; a turn would load it")
    if os.path.lexists(policy):
        raise HarnessStop(f"{policy} exists; a turn would load it")


class RealTurn:
    """The real `call_turn`: prepares the machine, runs the frozen invocation, and classifies its stream-json.

    Before every turn: the binaries exist, no instruction file sits above the working directory, the working
    directory and the wrapper's home/ and uv-cache/ are made fresh and empty, and the config directory is reset to
    the sign-in's files. Reading: the spec makes only the working directory fresh for every turn; home/ and uv-cache/
    are made fresh too, so no turn can leave anything for the next.

    The stream is captured outside the wrapper; when `transcripts` is given, each call's stream is written there.
    The scope is stopped after every call."""

    def __init__(
        self,
        signin_files: Iterable[str],
        *,
        wrapper: Wrapper = FROZEN,
        transcripts: str | os.PathLike | None = None,
        backstop_seconds: float = 30.0,
    ) -> None:
        self.signin_files = frozenset(signin_files)
        self.wrapper = wrapper
        self.transcripts = Path(transcripts) if transcripts is not None else None
        self.backstop_seconds = backstop_seconds
        self.sequence = 0

    def prepare(self) -> None:
        w = self.wrapper
        for binary in (w.claude, w.uv, w.uvx):
            if not os.access(binary, os.X_OK):
                raise HarnessStop(f"{binary} isn't an executable")
        check_no_instructions()
        _fresh_dir(w.turn_dir)
        _fresh_dir(w.home_dir)
        os.mkdir(os.path.join(w.home_dir, "home"), 0o700)
        os.mkdir(os.path.join(w.home_dir, "uv-cache"), 0o700)
        if Path(w.config_dir).is_symlink() or not Path(w.config_dir).is_dir():
            raise HarnessStop(f"{w.config_dir} isn't the sign-in's directory")
        reset_config(w.config_dir, self.signin_files)

    def __call__(self, prompt_text: str) -> TurnResult:
        self.prepare()
        self.sequence += 1
        unit = f"t4b-turn-{uuid.uuid4().hex[:12]}"
        argv = turn_argv(prompt_text, unit=unit, wrapper=self.wrapper)
        started = time.monotonic()
        killed = False
        returncode: int | None = None

        def text_of(value: Any) -> str:
            value = value or ""
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value

        try:
            proc = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.wrapper.timeout + self.backstop_seconds,
                check=False,
            )
            stream, errors, returncode = proc.stdout, proc.stderr, proc.returncode
            killed = proc.returncode == 124  # timeout(1)'s code when it killed the command
        except subprocess.TimeoutExpired as exc:
            stream, errors = text_of(exc.stdout), text_of(exc.stderr)
            killed = True  # the backstop, should timeout(1) itself not end the call
        finally:
            subprocess.run(
                ["systemctl", "--user", "stop", f"{unit}.scope"], capture_output=True, check=False, timeout=30
            )
        seconds = time.monotonic() - started
        digest = hashlib.sha256(stream.encode("utf-8")).hexdigest()
        if self.transcripts is not None:
            self.transcripts.mkdir(parents=True, exist_ok=True)
            _write(self.transcripts / f"{self.sequence:06d}-{unit}.jsonl", stream)
            _write(self.transcripts / f"{self.sequence:06d}-{unit}.stderr", errors)
        return classify(stream, killed=killed, seconds=seconds, transcript_sha256=digest, returncode=returncode)
