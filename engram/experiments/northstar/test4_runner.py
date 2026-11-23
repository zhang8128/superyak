"""North-star test 4, stage A: the runner and the scorer.

Written blind from two sections of the approved spec and nothing else: "The
contract (stage A)" (sha256 f0971788...) and "Stage A: argued, checked" (sha256
e48ce781...). It never reads either half's code. It imports the world half and
the policy half by the module names it is given, lazily, and uses only what the
contract says each exports: ``worlds()``, ``named`` and ``false_named`` from the
world half; ``fixed``, ``random``, ``adaptive_name`` and ``adaptive_content``
from the policy half; policy seeds 0 to 19; the trap-to-flag map.

What it does (stage A, "argued, checked"):

* runs every policy in every world (800: 4 traps x 100 trapped worlds and their
  twins) for each of the 20 policy seeds, one run at most ``budget`` turns,
  stopping at the first turn whose state passes ``recovered``;
* logs every call's flags, so ``flags_per_call[i]`` is the flags of the call
  made with a record of length ``i``, and applies each world's ``named`` (and
  ``false_named`` on twin runs);
* the ceiling: per policy and world, the trap effect (recovery rate in the
  trapped world minus its twin's, over the 20 paired seeds); per pair, the mean
  over the trap's 100 worlds of the difference in trap effects, with a 95%
  bootstrap CI over worlds (10,000 resamples, one index matrix per trap from a
  fresh ``numpy.random.default_rng(20261130)``, shared by every pair in that
  trap, ``numpy.quantile`` linear at 0.025 and 0.975);
* naming beside the ceiling, never inside it: per trap and policy, named on
  exposure, the false-name rate in the twins and the runs not exposed;
* activity beside the scores, never scored: turns used and distinct contents
  tried, in runs that recover and runs that don't;
* stage B's traps: traps 1, 2 and 4 go if any pair's CI excludes zero; trap 3
  (the summary trap) goes by the reads clause.

Two policies picking different approaches counts for nothing here: only
recovery enters the ceiling.

The runner refuses to start without the worlds' code hash, the policies' code
hash and the 800-world fingerprint, and refuses unless the world half's own
``fingerprint()`` equals the fingerprint given. The code hashes are recorded as
given: nothing defines how to compute them.

Interface facts from the halves' authors, beyond the contract: the halves are
``experiments.northstar.test4_worlds`` and ``experiments.northstar.test4_policies``;
``worlds()`` yields ``World`` objects carrying ``.trap``, ``.D``, ``.k``, ``.w``,
``.form`` and ``.budget``; twins join on ``(trap, D, k, w)``; a world's seed is
``numpy.random.SeedSequence([SEED_BASE, trap, D, k, w])``, which only confirms a
pairing; ``fingerprint() -> str``; ``named`` answering None (not exposed, or no
such call) is not counted.

Run from ``engram/``::

    python -m experiments.northstar.test4_runner \\
        --worlds-code-hash <hash> --policies-code-hash <hash> \\
        --fingerprint <800-world fingerprint> --out result.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import operator
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

SPEC_SECTIONS = {"the_contract_stage_a": "f0971788", "stage_a_argued_checked": "e48ce781"}
DEFAULT_WORLDS_MODULE = "experiments.northstar.test4_worlds"
DEFAULT_POLICIES_MODULE = "experiments.northstar.test4_policies"

START_STATE = "L0"
TRAPS = (1, 2, 3, 4)
# The trap-to-flag map, from the contract's false_named: cycle for trap 1,
# repeat for 2, contradiction for 3 and premise for 4.
TRAP_FLAG = {1: "cycle", 2: "repeat", 3: "contradiction", 4: "premise"}
FLAG_VALUE_KIND = {"repeat": "content", "cycle": "state", "contradiction": "turn", "premise": "turn"}
FORMS = ("trapped", "twin")
POLICY_NAMES = ("fixed", "random", "adaptive_name", "adaptive_content")
POLICY_SEEDS = tuple(range(20))
WORLDS_PER_TRAP = 100
WORLD_COUNT = len(TRAPS) * WORLDS_PER_TRAP * len(FORMS)
# Each adaptive policy against fixed and against random, and adaptive by name
# against adaptive by content. The difference is the first's trap effect minus
# the second's.
PAIRS = (
    ("adaptive_name", "fixed"),
    ("adaptive_name", "random"),
    ("adaptive_content", "fixed"),
    ("adaptive_content", "random"),
    ("adaptive_name", "adaptive_content"),
)
# The cycle, the renamed idea and the map-breaking observation go to stage B by
# the CI rule; the summary trap goes by the reads clause.
CI_RULE_TRAPS = (1, 2, 4)
READS_CLAUSE_TRAPS = (3,)
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261130
CI_LEVELS = (0.025, 0.975)
VERDICTS = ("pass", "fail")
SAYS = ("worked", "failed")
ENTRY_KEYS = ("turn", "state", "name", "content", "verdict", "summary", "observation")
WORLD_ENTRY_KEYS = frozenset(ENTRY_KEYS) - {"turn"}
WORLD_FIELDS = ("trap", "D", "k", "w", "form")
SEED_WORDS = 8  # how much of a recomputed SeedSequence's state confirms a pairing
RUN_COLUMNS = (
    "trap", "world", "form", "policy", "seed", "recovered", "turns_to_recovery",
    "turns_used", "distinct_contents", "named", "false_named", "flags_per_call",
)


class Refused(Exception):
    """The runner won't start: a required input is missing."""


class ContractError(Exception):
    """A half broke the contract's interface or its exact forms."""


# ---------------------------------------------------------------- provenance


def check_provenance(worlds_code_hash: Any, policies_code_hash: Any, worlds_fingerprint: Any) -> dict[str, str]:
    """Refuse unless all three are given, before importing either half."""
    given = {
        "worlds_code_hash": worlds_code_hash,
        "policies_code_hash": policies_code_hash,
        "worlds_fingerprint": worlds_fingerprint,
    }
    missing = [key for key, value in given.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise Refused("refusing to run stage A without " + ", ".join(missing))
    return dict(given)


def check_fingerprint(world_half: Any, given: str) -> str:
    """The world half's own fingerprint() must equal the one given."""
    computed = world_half.fingerprint()
    if not isinstance(computed, str):
        raise ContractError(f"fingerprint() returned {type(computed).__name__}, not a string")
    if computed != given:
        raise Refused(f"refusing to run stage A: the worlds' fingerprint() is {computed!r}, not the given {given!r}")
    return computed


# ------------------------------------------------------------------ loading


def load_halves(worlds_module: str, policies_module: str) -> tuple[Any, dict[str, Callable]]:
    """Import both halves by name, only now, and check each exports what the
    contract and the interface facts say it does."""
    world_half = importlib.import_module(worlds_module)
    policy_half = importlib.import_module(policies_module)
    for name in ("worlds", "named", "false_named", "fingerprint"):
        if not callable(getattr(world_half, name, None)):
            raise ContractError(f"the world half {worlds_module!r} doesn't export {name}()")
    if not hasattr(world_half, "SEED_BASE"):
        raise ContractError(f"the world half {worlds_module!r} doesn't export SEED_BASE")
    policies = {}
    for name in POLICY_NAMES:
        policy = getattr(policy_half, name, None)
        if not callable(policy):
            raise ContractError(f"the policy half {policies_module!r} doesn't export {name}")
        policies[name] = policy
    # POLICIES and SEEDS only confirm what the contract already fixes: the four
    # named functions and seeds 0 to 19.
    exported = getattr(policy_half, "POLICIES", None)
    if not isinstance(exported, Mapping) or set(exported) != set(POLICY_NAMES) or any(
        exported[name] is not policies[name] for name in POLICY_NAMES
    ):
        raise ContractError(f"the policy half's POLICIES isn't the four named functions by name: {exported!r}")
    seeds = getattr(policy_half, "SEEDS", None)
    if seeds is None or list(seeds) != list(POLICY_SEEDS):
        raise ContractError(f"the policy half's SEEDS is {seeds!r}, not the contract's 0 to 19")
    return world_half, policies


@dataclass(frozen=True)
class WorldItem:
    world: Any
    trap: int
    D: Any
    k: Any
    w: Any
    form: str


@dataclass(frozen=True)
class WorldPair:
    trap: int
    index: int  # its place among the trap's trapped worlds, in worlds() order
    D: Any
    k: Any
    w: Any
    trapped: Any
    twin: Any


def read_world(world: Any) -> WorldItem:
    """One World from worlds(): its .trap, .D, .k, .w and .form."""
    missing = [name for name in WORLD_FIELDS if not hasattr(world, name)]
    if missing:
        raise ContractError(f"a world from worlds() has no {', '.join('.' + m for m in missing)}")
    trap = world.trap
    if isinstance(trap, (bool, np.bool_)) or not isinstance(trap, (int, np.integer)) or int(trap) not in TRAPS:
        raise ContractError(f"a world's trap is {trap!r}; the contract's traps are 1 to 4")
    if world.form not in FORMS:
        raise ContractError(f"a world's form is {world.form!r}; the contract's are trapped or twin")
    return WorldItem(world, int(trap), world.D, world.k, world.w, world.form)


def world_seed(world_half: Any, item: WorldItem) -> tuple[int, ...]:
    """The seed the world half builds a world from, recomputed from the world's
    own attributes: SeedSequence([SEED_BASE, trap, D, k, w])."""
    world = item.world
    try:
        sequence = np.random.SeedSequence([world_half.SEED_BASE, world.trap, world.D, world.k, world.w])
    except (TypeError, ValueError) as exc:
        raise ContractError(f"can't recompute the seed of trap {item.trap}, D, k, w {item.D!r}, {item.k!r}, {item.w!r}") from exc
    return tuple(sequence.generate_state(SEED_WORDS).tolist())


def collect_worlds(world_half: Any) -> dict[int, list[WorldPair]]:
    """Every World from worlds(), each trapped world joined to its twin: the one
    with the same trap, D, k and w. Never joined on order. Each pair is then
    confirmed by recomputing both worlds' seeds. Refuses anything but 4 traps x
    100 one-to-one pairs whose seeds agree."""
    items = [read_world(world) for world in world_half.worlds()]
    if len(items) != WORLD_COUNT:
        raise ContractError(f"worlds() yielded {len(items)} worlds; stage A needs {WORLD_COUNT}")

    def key_of(item: WorldItem) -> tuple:
        key = (item.trap, item.D, item.k, item.w)
        try:
            hash(key)
        except TypeError as exc:
            raise ContractError(f"a world's trap, D, k and w can't key a twin: {key!r}") from exc
        return key

    groups: dict[tuple, dict[str, list[WorldItem]]] = {}
    for item in items:
        groups.setdefault(key_of(item), {"trapped": [], "twin": []})[item.form].append(item)
    for key, slot in groups.items():
        if len(slot["trapped"]) != 1 or len(slot["twin"]) != 1:
            raise ContractError(
                f"no one-to-one twin for trap, D, k, w {key!r}: "
                f"{len(slot['trapped'])} trapped, {len(slot['twin'])} twin"
            )
    pairs: dict[int, list[WorldPair]] = {trap: [] for trap in TRAPS}
    for it in items:
        if it.form != "trapped":
            continue
        key = key_of(it)
        twin = groups[key]["twin"][0]
        if world_seed(world_half, it) != world_seed(world_half, twin):
            raise ContractError(f"refusing a twin pair whose recomputed seeds differ: trap, D, k, w {key!r}")
        pairs[it.trap].append(WorldPair(it.trap, len(pairs[it.trap]), it.D, it.k, it.w, it.world, twin.world))
    for trap in TRAPS:
        if len(pairs[trap]) != WORLDS_PER_TRAP:
            raise ContractError(f"trap {trap} has {len(pairs[trap])} worlds; stage A needs {WORLDS_PER_TRAP}")
    return pairs


# --------------------------------------------------------------------- runs


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _whole(value: Any, what: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ContractError(f"{what} is a bool, not a number")
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ContractError(f"{what} is {value!r}, not a whole number") from exc


def _budget(world: Any) -> int:
    budget = _whole(getattr(world, "budget", None), "a world's budget")
    if budget < 0:
        raise ContractError(f"a world's budget is {budget}")
    return budget


def _options(world: Any, state: str) -> list[dict]:
    options = list(world.options(state))
    for option in options:
        if not (
            isinstance(option, dict)
            and set(option) == {"name", "content"}
            and isinstance(option["name"], str)
            and isinstance(option["content"], str)
        ):
            raise ContractError(f"an option in state {state!r} isn't {{'name': str, 'content': str}}: {option!r}")
    return options


def check_flags(flags: Any) -> list[dict]:
    """A list of one-key dicts: repeat holds a content, cycle a state id, and
    contradiction and premise a turn number."""
    if not isinstance(flags, (list, tuple)):
        raise ContractError(f"a policy's flags are {type(flags).__name__}, not a list")
    checked = []
    for flag in flags:
        if not isinstance(flag, dict) or len(flag) != 1:
            raise ContractError(f"a flag isn't a one-key dict: {flag!r}")
        ((key, value),) = flag.items()
        kind = FLAG_VALUE_KIND.get(key)
        if kind is None:
            raise ContractError(f"{key!r} isn't one of the contract's flags")
        if kind == "turn":
            value = _whole(value, f"a {key} flag's turn")
        elif not isinstance(value, str):
            raise ContractError(f"a {key} flag holds {value!r}, not a string")
        else:
            value = str(value)
        checked.append({key: value})
    return checked


def _policy_answer(answer: Any, option_count: int) -> tuple[int, list[dict]]:
    if not isinstance(answer, (tuple, list)) or len(answer) != 2:
        raise ContractError(f"a policy returned {answer!r}, not (index, flags)")
    index = _whole(answer[0], "a policy's index")
    if not 0 <= index < option_count:
        raise ContractError(f"a policy's index {index} doesn't point into {option_count} options")
    return index, check_flags(answer[1])


def _check_entry(entry: Any, approach: dict, next_state: Any, turn: int) -> dict:
    """The world's entry in the record's exact form, with the runner's turn."""
    if not isinstance(entry, dict):
        raise ContractError(f"step returned an entry of type {type(entry).__name__}")
    keys = set(entry)
    if not WORLD_ENTRY_KEYS <= keys <= set(ENTRY_KEYS):
        raise ContractError(f"an entry's keys are {sorted(keys)}; the record's are {list(ENTRY_KEYS)}")
    state = entry["state"]
    if not isinstance(state, str):
        raise ContractError(f"an entry's state is {state!r}, not a state id")
    if next_state != state:
        raise ContractError(f"step's next state {next_state!r} isn't its entry's state {state!r}")
    if entry["name"] != approach["name"] or entry["content"] != approach["content"]:
        raise ContractError("an entry's name and content aren't the approach that was taken")
    if entry["verdict"] not in VERDICTS:
        raise ContractError(f"an entry's verdict is {entry['verdict']!r}")
    summary = entry["summary"]
    if not (
        isinstance(summary, dict)
        and set(summary) == {"approach", "says"}
        and summary["approach"] == entry["content"]
        and summary["says"] in SAYS
    ):
        raise ContractError(f"an entry's summary isn't {{'approach': content, 'says': worked|failed}}: {summary!r}")
    observation = entry["observation"]
    if observation is not None:
        invalidates = observation.get("invalidates") if isinstance(observation, dict) else None
        if not (
            isinstance(observation, dict)
            and set(observation) == {"invalidates"}
            and isinstance(invalidates, (list, tuple))
            and all(isinstance(content, str) for content in invalidates)
        ):
            raise ContractError(f"an entry's observation isn't None or {{'invalidates': [content]}}: {observation!r}")
        observation = {"invalidates": list(invalidates)}
    return {
        "turn": turn,
        "state": state,
        "name": entry["name"],
        "content": entry["content"],
        "verdict": entry["verdict"],
        "summary": {"approach": summary["approach"], "says": summary["says"]},
        "observation": observation,
    }


def _recovered(world: Any, state: str) -> bool:
    answer = world.recovered(state)
    if not isinstance(answer, (bool, np.bool_)):
        raise ContractError(f"recovered({state!r}) returned {answer!r}, not a bool")
    return bool(answer)


@dataclass
class Run:
    record: list[dict]
    flags_per_call: list[list[dict]]
    recovered: bool
    turns_to_recovery: int | None

    @property
    def turns_used(self) -> int:
        return len(self.record)

    @property
    def distinct_contents(self) -> int:
        return len({entry["content"] for entry in self.record})


def run_one(world: Any, policy: Callable, seed: int) -> Run:
    """One policy in one world for at most ``budget`` turns, stopping at the
    first turn whose state passes ``recovered``. The policy gets a copy of the
    record so far, a copy of the current state's options and the seed; its
    flags go nowhere near the world."""
    budget = _budget(world)
    entry_texts: list[str] = []
    flags_per_call: list[list[dict]] = []
    state = START_STATE
    recovered_at = None
    for turn in range(1, budget + 1):
        options = _options(world, state)
        record_so_far = json.loads("[" + ",".join(entry_texts) + "]")
        index, flags = _policy_answer(policy(record_so_far, _json_copy(options), seed), len(options))
        flags_per_call.append(flags)  # the call made with a record of length turn - 1
        approach = options[index]
        stepped = world.step(state, approach)
        if not isinstance(stepped, (tuple, list)) or len(stepped) != 2:
            raise ContractError("step didn't return (next state, entry)")
        entry = _check_entry(stepped[1], approach, stepped[0], turn)
        entry_texts.append(json.dumps(entry, allow_nan=False))
        state = entry["state"]
        if _recovered(world, state):
            recovered_at = turn
            break
    record = json.loads("[" + ",".join(entry_texts) + "]")
    return Run(record, flags_per_call, recovered_at is not None, recovered_at)


def trap_flag_raised(trap: int, flags_per_call: Sequence[Sequence[dict]]) -> bool:
    """The trap's flag, with any value, at any call: the runner's own reading
    of a false name, checked against the world half's false_named."""
    flag = TRAP_FLAG[trap]
    return any(flag in raised for call in flags_per_call for raised in call)


def apply_named(world_half: Any, world: Any, run: Run) -> bool | None:
    answer = world_half.named(world, _json_copy(run.record), _json_copy(run.flags_per_call))
    if answer is not None and answer is not True and answer is not False:
        raise ContractError(f"named returned {answer!r}, not True, False or None")
    return answer


def apply_false_named(world_half: Any, world: Any, run: Run) -> bool:
    answer = world_half.false_named(world, _json_copy(run.record), _json_copy(run.flags_per_call))
    if not isinstance(answer, (bool, np.bool_)):
        raise ContractError(f"false_named returned {answer!r}, not a bool")
    return bool(answer)


# ------------------------------------------------------------------ scoring


def recovery_rate(recovered: Sequence[bool]) -> float:
    """One policy's recovery rate in one world: over its 20 seeds."""
    if len(recovered) != len(POLICY_SEEDS):
        raise ValueError(f"a recovery rate is over {len(POLICY_SEEDS)} seeds, not {len(recovered)}")
    return sum(1 for r in recovered if r) / len(POLICY_SEEDS)


def trap_effect(trapped: Sequence[bool], twin: Sequence[bool]) -> float:
    """The recovery rate in the trapped world minus the rate in its twin."""
    return recovery_rate(trapped) - recovery_rate(twin)


def resample_matrix(world_count: int) -> np.ndarray:
    """One trap's resample matrix of world indices, from a fresh generator."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    return rng.integers(0, world_count, size=(BOOTSTRAP_RESAMPLES, world_count))


def pair_ceiling(differences: np.ndarray, matrix: np.ndarray) -> dict:
    """The mean over worlds and its 95% percentile bootstrap CI."""
    means = differences[matrix].mean(axis=1)
    low, high = np.quantile(means, CI_LEVELS, method="linear")
    return {
        "mean": float(differences.mean()),
        "ci": [float(low), float(high)],
        "excludes_zero": bool(low > 0 or high < 0),
    }


def trap_ceiling(effects: Mapping[str, np.ndarray]) -> list[dict]:
    """Every pair in one trap, all sharing the trap's one resample matrix."""
    matrix = resample_matrix(len(effects[POLICY_NAMES[0]]))
    return [
        {"a": a, "b": b, **pair_ceiling(np.asarray(effects[a]) - np.asarray(effects[b]), matrix)}
        for a, b in PAIRS
    ]


def choose_stage_b(ceiling: Mapping[int, Sequence[dict]]) -> dict[int, dict]:
    """A trap goes to stage B if any pair's CI excludes zero; the summary trap
    goes by the reads clause instead."""
    chosen = {}
    for trap in TRAPS:
        excluding = [f"{pair['a']} - {pair['b']}" for pair in ceiling[trap] if pair["excludes_zero"]]
        if trap in READS_CLAUSE_TRAPS:
            chosen[trap] = {"rule": "reads clause", "goes_to_b": True, "pairs_excluding_zero": excluding}
        else:
            chosen[trap] = {"rule": "ci", "goes_to_b": bool(excluding), "pairs_excluding_zero": excluding}
    return chosen


def naming_summary(trapped_named: Sequence[bool | None], twin_false_named: Sequence[bool]) -> dict:
    """Named on exposure over the trapped runs whose rule answered; the runs
    not exposed are those it answered None; false names over the twin runs."""
    exposed = [answer for answer in trapped_named if answer is not None]
    named = sum(1 for answer in exposed if answer)
    false_names = sum(1 for answer in twin_false_named if answer)
    return {
        "trapped_runs": len(trapped_named),
        "exposed": len(exposed),
        "named": named,
        "named_on_exposure": named / len(exposed) if exposed else None,
        "not_exposed": len(trapped_named) - len(exposed),
        "twin_runs": len(twin_false_named),
        "false_names": false_names,
        "false_name_rate": false_names / len(twin_false_named) if twin_false_named else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def activity_summary(runs: Sequence[dict]) -> dict:
    """Turns used and distinct contents tried, in runs that recover and runs
    that don't. Reported, never scored."""
    out = {}
    for label, recovered in (("recovered", True), ("not_recovered", False)):
        chosen = [run for run in runs if run["recovered"] is recovered]
        out[label] = {
            "runs": len(chosen),
            "mean_turns_used": _mean([run["turns_used"] for run in chosen]),
            "mean_distinct_contents": _mean([run["distinct_contents"] for run in chosen]),
        }
    return out


def recovery_summary(runs: Sequence[dict]) -> dict:
    recovered = [run for run in runs if run["recovered"]]
    return {
        "runs": len(runs),
        "recovered": len(recovered),
        "rate": len(recovered) / len(runs) if runs else None,
        "mean_turns_to_recovery": _mean([run["turns_to_recovery"] for run in recovered]),
    }


# -------------------------------------------------------------------- stage A


def run_stage_a(
    *,
    worlds_code_hash: Any,
    policies_code_hash: Any,
    worlds_fingerprint: Any,
    worlds_module: str = DEFAULT_WORLDS_MODULE,
    policies_module: str = DEFAULT_POLICIES_MODULE,
) -> dict:
    provenance = check_provenance(worlds_code_hash, policies_code_hash, worlds_fingerprint)
    world_half, policies = load_halves(worlds_module, policies_module)
    computed_fingerprint = check_fingerprint(world_half, provenance["worlds_fingerprint"])
    pairs = collect_worlds(world_half)

    rows: list[dict] = []
    ceiling: dict[int, dict] = {}
    naming: dict[int, dict] = {}
    recovery: dict[int, dict] = {}
    activity: dict[int, dict] = {}
    counts = {"runs": 0, "recovery_checks": 0, "named_calls": 0, "false_named_calls": 0, "policy_calls": 0}
    disagreements: dict[int, dict[str, int]] = {}

    for trap in TRAPS:
        effects = {name: np.empty(WORLDS_PER_TRAP) for name in POLICY_NAMES}
        trap_rows: dict[tuple[str, str], list[dict]] = {(f, p): [] for f in FORMS for p in POLICY_NAMES}
        disagreements[trap] = {name: 0 for name in POLICY_NAMES}
        for pair in pairs[trap]:
            for name in POLICY_NAMES:
                recovered_by_form: dict[str, list[bool]] = {}
                for form, world in (("trapped", pair.trapped), ("twin", pair.twin)):
                    recovered_by_form[form] = []
                    for seed in POLICY_SEEDS:
                        run = run_one(world, policies[name], seed)
                        named = apply_named(world_half, world, run)
                        counts["named_calls"] += 1
                        false_named = None
                        if form == "twin":
                            false_named = apply_false_named(world_half, world, run)
                            counts["false_named_calls"] += 1
                            if false_named != trap_flag_raised(trap, run.flags_per_call):
                                disagreements[trap][name] += 1
                        counts["runs"] += 1
                        counts["recovery_checks"] += run.turns_used
                        counts["policy_calls"] += len(run.flags_per_call)
                        row = {
                            "trap": trap,
                            "world": pair.index,
                            "form": form,
                            "policy": name,
                            "seed": seed,
                            "recovered": run.recovered,
                            "turns_to_recovery": run.turns_to_recovery,
                            "turns_used": run.turns_used,
                            "distinct_contents": run.distinct_contents,
                            "named": named,
                            "false_named": false_named,
                            "flags_per_call": run.flags_per_call,
                        }
                        rows.append(row)
                        trap_rows[(form, name)].append(row)
                        recovered_by_form[form].append(run.recovered)
                effects[name][pair.index] = trap_effect(recovered_by_form["trapped"], recovered_by_form["twin"])
        ceiling[trap] = {
            "trap_effects": {name: [float(x) for x in effects[name]] for name in POLICY_NAMES},
            "mean_trap_effect": {name: float(effects[name].mean()) for name in POLICY_NAMES},
            "pairs": trap_ceiling(effects),
        }
        naming[trap] = {}
        for name in POLICY_NAMES:
            summary = naming_summary(
                [row["named"] for row in trap_rows[("trapped", name)]],
                [row["false_named"] for row in trap_rows[("twin", name)]],
            )
            summary["false_named_disagrees_with_flag_map"] = disagreements[trap][name]
            naming[trap][name] = summary
        recovery[trap] = {f: {p: recovery_summary(trap_rows[(f, p)]) for p in POLICY_NAMES} for f in FORMS}
        activity[trap] = {f: {p: activity_summary(trap_rows[(f, p)]) for p in POLICY_NAMES} for f in FORMS}

    stage_b = choose_stage_b({trap: ceiling[trap]["pairs"] for trap in TRAPS})
    return {
        "experiment": "north-star test 4",
        "stage": "A",
        "label": "argued, checked",
        "spec_sections": SPEC_SECTIONS,
        "provenance": {
            **provenance,
            "worlds_module": worlds_module,
            "policies_module": policies_module,
            "worlds_fingerprint_computed": computed_fingerprint,
            "fingerprint_check": "the worlds' fingerprint() equals the one given",
            "code_hash_check": "given, not recomputed: nothing defines how to compute a code hash",
            "seed_base": world_half.SEED_BASE,
            "twin_seeds_confirmed": sum(len(pairs[trap]) for trap in TRAPS),
            "numpy": np.__version__,
        },
        "design": {
            "traps": list(TRAPS),
            "trap_flag": {str(trap): flag for trap, flag in TRAP_FLAG.items()},
            "worlds_per_trap": WORLDS_PER_TRAP,
            "policies": list(POLICY_NAMES),
            "policy_seeds": list(POLICY_SEEDS),
            "pairs": [[a, b] for a, b in PAIRS],
            "difference": "trap effect of a minus trap effect of b",
            "bootstrap": {
                "resamples": BOOTSTRAP_RESAMPLES,
                "rng": f"numpy.random.default_rng({BOOTSTRAP_SEED}), fresh per trap",
                "draw": "rng.integers(0, worlds, size=(resamples, worlds))",
                "quantiles": list(CI_LEVELS),
                "method": "linear",
            },
            "ci_rule_traps": list(CI_RULE_TRAPS),
            "reads_clause_traps": list(READS_CLAUSE_TRAPS),
        },
        "worlds": {
            str(trap): [{"index": p.index, "D": p.D, "k": p.k, "w": p.w} for p in pairs[trap]]
            for trap in TRAPS
        },
        "ceiling": {str(trap): ceiling[trap] for trap in TRAPS},
        "naming": {str(trap): naming[trap] for trap in TRAPS},
        "stage_b": {str(trap): stage_b[trap] for trap in TRAPS},
        "scorer_test": {
            "worlds": WORLD_COUNT,
            "policies": len(POLICY_NAMES),
            "seeds": len(POLICY_SEEDS),
            **counts,
        },
        "recovery": {str(trap): recovery[trap] for trap in TRAPS},
        "activity": {str(trap): activity[trap] for trap in TRAPS},
        "runs": {"columns": list(RUN_COLUMNS), "rows": [[row[c] for c in RUN_COLUMNS] for row in rows]},
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"{type(value).__name__} isn't JSON")


def write_result(result: dict, out: Path) -> None:
    text = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default)
    out.write_text(text + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="North-star test 4, stage A: run and score.")
    parser.add_argument("--worlds-module", default=DEFAULT_WORLDS_MODULE, help="the world half's module name")
    parser.add_argument("--policies-module", default=DEFAULT_POLICIES_MODULE, help="the policy half's module name")
    parser.add_argument("--worlds-code-hash", required=True)
    parser.add_argument("--policies-code-hash", required=True)
    parser.add_argument("--fingerprint", required=True, help="the 800-world fingerprint; must equal fingerprint()")
    parser.add_argument("--out", required=True, type=Path, help="where the one JSON result goes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_stage_a(
            worlds_module=args.worlds_module,
            policies_module=args.policies_module,
            worlds_code_hash=args.worlds_code_hash,
            policies_code_hash=args.policies_code_hash,
            worlds_fingerprint=args.fingerprint,
        )
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except ContractError as exc:
        print(f"contract: {exc}", file=sys.stderr)
        return 3
    write_result(result, args.out)
    print(f"stage A result: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
