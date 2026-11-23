"""World half for Stage A, Test 4 (the four traps).

Built from "The contract" and "The worlds" alone, per the pre-registered
spec for this experiment. This module owns only the world half: it knows
nothing about any policy, runner or scorer.

Exports:
    worlds()      -- yields all 800 World objects (4 traps x 2 depths x
                      2 widths x 25 seeds x 2 forms).
    named(...)    -- the frozen naming rule for a run's record.
    false_named(...) -- whether a trap's flag fired, with any value, in a
                      twin run's record.
    TRAP_FLAGS    -- the trap-to-flag map.

Each World exposes the contract's world interface: options(state),
step(state, approach), recovered(state), and the plain attribute budget.
Every world is a static table (see "The fingerprint"); a World simply
wraps that table.
"""

import hashlib
import json

import numpy as np

# The 64 neutral words, in the fixed list order. The pool for a (trap, D,
# k, w) combination takes the first 2k of these, in order; a trap-2 world's
# renamed returner takes the unused words from word 2k onward, also in order.
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
assert len(WORDS) == 64

SEED_BASE = 20261129

TRAP_CYCLE = 1
TRAP_RENAME = 2
TRAP_SUMMARY = 3
TRAP_MAP = 4

# The trap-to-flag map (review 2's required export).
TRAP_FLAGS = {
    TRAP_CYCLE: "cycle",
    TRAP_RENAME: "repeat",
    TRAP_SUMMARY: "contradiction",
    TRAP_MAP: "premise",
}

D_VALUES = (4, 8)
K_VALUES = (3, 5)
W_VALUES = tuple(range(25))
FORMS = ("trapped", "twin")


def _idea_content(trap, D, k, w, i):
    digest = hashlib.sha256(f"{trap}:{D}:{k}:{w}:{i}".encode("utf-8")).hexdigest()
    return digest[:16]


def _level_state(d):
    return f"L{d}"


def _parse_level(state):
    """The level number of a state like "L3", or None for "G", "C1".."C3"."""
    if len(state) >= 2 and state[0] == "L" and state[1:].isdigit():
        return int(state[1:])
    return None


class World:
    """A single built world (trapped or its twin). See "The contract"."""

    def __init__(self, trap, D, k, w, form, states, budget, info):
        self.trap = trap
        self.D = D
        self.k = k
        self.w = w
        self.form = form
        self.budget = budget
        # state -> {"options": [(name, content), ...],
        #           "step": {content: (next_state, verdict, says, invalidates_or_None)}}
        self._states = states
        # trap-specific metadata used only by named()/false_named() and by
        # this module's own tests (never read by a policy).
        self._info = info

    def options(self, state):
        if state not in self._states:
            return []
        return [{"name": n, "content": c} for (n, c) in self._states[state]["options"]]

    def step(self, state, approach):
        content = approach["content"]
        name = approach.get("name")
        next_state, verdict, says, invalidates = self._states[state]["step"][content]
        entry = {
            "state": next_state,
            "name": name,
            "content": content,
            "verdict": verdict,
            "summary": {"approach": content, "says": says},
            "observation": {"invalidates": list(invalidates)} if invalidates else None,
        }
        return next_state, entry

    def recovered(self, state):
        return state == "G"


def _base_draws(trap, D, k, w):
    """The key and every level's option order (items 1-2 of "The order of draws").

    Returns (rng, P, key, nonkey_all, levels_options) with the rng advanced
    past these draws, ready for a trap's own draws (item 3).
    """
    seed_seq = np.random.SeedSequence([SEED_BASE, trap, D, k, w])
    rng = np.random.default_rng(seed_seq)
    P = 2 * k
    key = int(rng.integers(P))
    nonkey_all = np.array([i for i in range(P) if i != key], dtype=np.int64)
    levels_options = []
    for _d in range(D):
        others = rng.choice(nonkey_all, size=k - 1, replace=False)
        combined = [key] + [int(x) for x in others]
        perm = rng.permutation(combined)
        levels_options.append([int(x) for x in perm])
    return rng, P, key, nonkey_all, levels_options


def _base_step_entry(d, D, i, key):
    """The base world's step outcome for idea i at level d, before any trap override."""
    next_on_pass = _level_state(d + 1) if d < D - 1 else "G"
    if i == key:
        return (next_on_pass, "pass", "worked", None)
    return (_level_state(d), "fail", "failed", None)


def _build_cycle_pair(trap, D, k, w, rng, key, levels_options):
    c = int(rng.integers(1, D - 1))  # 1 .. D-2
    Lc = _level_state(c)
    Lc_order = levels_options[c]
    nonkey_at_c = [i for i in Lc_order if i != key]
    lure = int(rng.choice(np.array(nonkey_at_c, dtype=np.int64)))
    c1_order = [int(x) for x in rng.permutation(Lc_order)]
    c2_order = [int(x) for x in rng.permutation(Lc_order)]
    c3_order = [int(x) for x in rng.permutation(Lc_order)]

    key_content = _idea_content(trap, D, k, w, key)
    lure_content = _idea_content(trap, D, k, w, lure)
    next_after_c = _level_state(c + 1)
    budget = 2 * D * k + 3

    def make_states(form):
        states = {}
        for d in range(D):
            order = levels_options[d]
            opts = [(WORDS[i], _idea_content(trap, D, k, w, i)) for i in order]
            step = {}
            for i in order:
                ci = _idea_content(trap, D, k, w, i)
                if d == c and i == lure:
                    step[ci] = ("C1", "pass", "worked", None)
                else:
                    step[ci] = _base_step_entry(d, D, i, key)
            states[_level_state(d)] = {"options": opts, "step": step}

        loop_defs = [
            ("C1", c1_order, "C2"),
            ("C2", c2_order, "C3"),
            ("C3", c3_order, Lc if form == "trapped" else next_after_c),
        ]
        for state_name, order, lure_next in loop_defs:
            opts = [(WORDS[i], _idea_content(trap, D, k, w, i)) for i in order]
            step = {}
            for i in order:
                ci = _idea_content(trap, D, k, w, i)
                if i == key:
                    step[ci] = (next_after_c, "pass", "worked", None)
                elif i == lure:
                    step[ci] = (lure_next, "pass", "worked", None)
                else:
                    step[ci] = (state_name, "fail", "failed", None)
            states[state_name] = {"options": opts, "step": step}
        return states

    info = {"c": c, "Lc": Lc, "key_content": key_content, "lure_content": lure_content}
    trapped = World(trap, D, k, w, "trapped", make_states("trapped"), budget, dict(info))
    twin = World(trap, D, k, w, "twin", make_states("twin"), budget, dict(info))
    return trapped, twin


def _build_rename_pair(trap, D, k, w, rng, key, levels_options, P):
    nonkey_at_0 = [i for i in levels_options[0] if i != key]
    returner = int(rng.choice(np.array(nonkey_at_0, dtype=np.int64)))
    for d in range(1, D):
        if returner not in levels_options[d]:
            candidate_positions = [p for p in range(k) if levels_options[d][p] != key]
            pos = int(rng.choice(np.array(candidate_positions, dtype=np.int64)))
            levels_options[d][pos] = returner

    returner_content = _idea_content(trap, D, k, w, returner)
    new_names = {}
    next_word = P
    for d in range(1, D):
        new_names[d] = WORDS[next_word]
        next_word += 1

    budget = 2 * D * k

    def make_states(form):
        states = {}
        for d in range(D):
            order = levels_options[d]
            opts = []
            for i in order:
                if form == "trapped" and d >= 1 and i == returner:
                    name = new_names[d]
                else:
                    name = WORDS[i]
                opts.append((name, _idea_content(trap, D, k, w, i)))
            step = {}
            for i in order:
                ci = _idea_content(trap, D, k, w, i)
                step[ci] = _base_step_entry(d, D, i, key)
            states[_level_state(d)] = {"options": opts, "step": step}
        return states

    info = {"returner_content": returner_content, "key_content": _idea_content(trap, D, k, w, key)}
    trapped = World(trap, D, k, w, "trapped", make_states("trapped"), budget, dict(info))
    twin = World(trap, D, k, w, "twin", make_states("twin"), budget, dict(info))
    return trapped, twin


def _build_summary_pair(trap, D, k, w, rng, key, nonkey_all, levels_options):
    n = max(1, len(nonkey_all) // 2)
    misled_arr = rng.choice(nonkey_all, size=n, replace=False)
    misled = set(int(x) for x in misled_arr)

    budget = 2 * D * k

    def make_states(form):
        states = {}
        for d in range(D):
            order = levels_options[d]
            opts = [(WORDS[i], _idea_content(trap, D, k, w, i)) for i in order]
            step = {}
            next_on_pass = _level_state(d + 1) if d < D - 1 else "G"
            for i in order:
                ci = _idea_content(trap, D, k, w, i)
                if i == key:
                    step[ci] = (next_on_pass, "pass", "worked", None)
                else:
                    says = "worked" if (form == "trapped" and i in misled) else "failed"
                    step[ci] = (_level_state(d), "fail", says, None)
            states[_level_state(d)] = {"options": opts, "step": step}
        return states

    info = {
        "misled_contents": set(_idea_content(trap, D, k, w, i) for i in misled),
        "key_content": _idea_content(trap, D, k, w, key),
    }
    trapped = World(trap, D, k, w, "trapped", make_states("trapped"), budget, dict(info))
    twin = World(trap, D, k, w, "twin", make_states("twin"), budget, dict(info))
    return trapped, twin


def _build_map_pair(trap, D, k, w, rng, key, nonkey_all, levels_options):
    m = int(rng.integers(2, D - 1))  # 2 .. D-2
    new_key = int(rng.choice(nonkey_all))
    for d in range(m, D):
        if new_key not in levels_options[d]:
            candidate_positions = [p for p in range(k) if levels_options[d][p] != key]
            pos = int(rng.choice(np.array(candidate_positions, dtype=np.int64)))
            levels_options[d][pos] = new_key

    key_content = _idea_content(trap, D, k, w, key)
    new_key_content = _idea_content(trap, D, k, w, new_key)
    Lm = _level_state(m)
    budget = 2 * D * k

    def make_states(form):
        states = {}
        for d in range(D):
            order = levels_options[d]
            opts = [(WORDS[i], _idea_content(trap, D, k, w, i)) for i in order]
            step = {}
            next_on_pass = _level_state(d + 1) if d < D - 1 else "G"
            for i in order:
                ci = _idea_content(trap, D, k, w, i)
                if form == "twin":
                    step[ci] = _base_step_entry(d, D, i, key)
                    continue
                if d < m:
                    if i == key:
                        inv = [key_content] if d == m - 1 else None
                        step[ci] = (next_on_pass, "pass", "worked", inv)
                    else:
                        step[ci] = (_level_state(d), "fail", "failed", None)
                else:  # d >= m, trapped: old key invalidated, new key advances
                    if i == key:
                        step[ci] = (_level_state(d), "fail", "failed", None)
                    elif i == new_key:
                        step[ci] = (next_on_pass, "pass", "worked", None)
                    else:
                        step[ci] = (_level_state(d), "fail", "failed", None)
            states[_level_state(d)] = {"options": opts, "step": step}
        return states

    info = {"m": m, "Lm": Lm, "key_content": key_content, "new_key_content": new_key_content}
    trapped = World(trap, D, k, w, "trapped", make_states("trapped"), budget, dict(info))
    twin = World(trap, D, k, w, "twin", make_states("twin"), budget, dict(info))
    return trapped, twin


def _build_pair(trap, D, k, w):
    rng, P, key, nonkey_all, levels_options = _base_draws(trap, D, k, w)
    if trap == TRAP_CYCLE:
        return _build_cycle_pair(trap, D, k, w, rng, key, levels_options)
    elif trap == TRAP_RENAME:
        return _build_rename_pair(trap, D, k, w, rng, key, levels_options, P)
    elif trap == TRAP_SUMMARY:
        return _build_summary_pair(trap, D, k, w, rng, key, nonkey_all, levels_options)
    elif trap == TRAP_MAP:
        return _build_map_pair(trap, D, k, w, rng, key, nonkey_all, levels_options)
    raise ValueError(f"unknown trap {trap}")


def worlds():
    """Yields all 800 worlds, trap 1..4, D, k, w, trapped then twin."""
    for trap in (TRAP_CYCLE, TRAP_RENAME, TRAP_SUMMARY, TRAP_MAP):
        for D in D_VALUES:
            for k in K_VALUES:
                for w in W_VALUES:
                    trapped, twin = _build_pair(trap, D, k, w)
                    yield trapped
                    yield twin


def _has_flag(flags, key, value):
    for f in flags:
        if key in f and f[key] == value:
            return True
    return False


def _named_cycle(world, record, flags_per_call):
    Lc = world._info["Lc"]
    prev_state = "L0"
    arrivals = []
    for idx, e in enumerate(record):
        if e["state"] != prev_state and e["state"] == Lc:
            arrivals.append(idx)
        prev_state = e["state"]
    if len(arrivals) < 2:
        return None
    # The call on an arrival is the one whose record ends with it: a record
    # of length arrivals[1] + 1, i.e. flags_per_call[arrivals[1] + 1]. The
    # call that chose the arriving step itself, flags_per_call[arrivals[1]],
    # was made before the arrival existed and cannot see it.
    call_idx = arrivals[1] + 1
    if call_idx >= len(flags_per_call):
        return None
    return _has_flag(flags_per_call[call_idx], "cycle", Lc)


def _named_rename(world, record, flags_per_call):
    target = world._info["returner_content"]
    tried_idx = None
    tried_name = None
    for idx, e in enumerate(record):
        if e["content"] == target:
            tried_idx = idx
            tried_name = e["name"]
            break
    if tried_idx is None:
        return None
    N = len(record)
    for i in range(tried_idx + 1, N):
        state_before = record[i - 1]["state"]
        offered_name = None
        for o in world.options(state_before):
            if o["content"] == target:
                offered_name = o["name"]
                break
        if offered_name is not None and offered_name != tried_name:
            if i >= len(flags_per_call):
                return None
            return _has_flag(flags_per_call[i], "repeat", target)
    return None


def _named_summary(world, record, flags_per_call):
    mismatch_idx = None
    for idx, e in enumerate(record):
        if e["verdict"] == "fail" and e["summary"]["says"] == "worked":
            mismatch_idx = idx
            break
    if mismatch_idx is None:
        return None
    turn = mismatch_idx + 1  # the mismatched turn, 1-indexed
    call_idx = turn  # the call just after it: flags_per_call[i] <-> record[i]
    if call_idx >= len(flags_per_call):
        return None
    return _has_flag(flags_per_call[call_idx], "contradiction", turn)


def _named_map(world, record, flags_per_call):
    Lm = world._info["Lm"]
    arrival_idx = None
    for idx, e in enumerate(record):
        if e["state"] == Lm:
            arrival_idx = idx
            break
    if arrival_idx is None:
        return None
    turn = arrival_idx + 1
    call_idx = turn
    if call_idx >= len(flags_per_call):
        return None
    return _has_flag(flags_per_call[call_idx], "premise", turn)


_NAMED_BY_TRAP = {
    TRAP_CYCLE: _named_cycle,
    TRAP_RENAME: _named_rename,
    TRAP_SUMMARY: _named_summary,
    TRAP_MAP: _named_map,
}


def named(world, record, flags_per_call):
    """The frozen naming rule for `world`'s trap. See "The worlds"."""
    return _NAMED_BY_TRAP[world.trap](world, record, flags_per_call)


def false_named(world, record, flags_per_call):
    """True if the trap's flag appears, with any value, at any call."""
    flag_key = TRAP_FLAGS[world.trap]
    for flags in flags_per_call:
        for f in flags:
            if flag_key in f:
                return True
    return False


def _world_to_dict(world):
    states = {}
    for state, sdata in world._states.items():
        opts = [[name, content] for (name, content) in sdata["options"]]
        step = {}
        for content, (next_state, verdict, says, invalidates) in sdata["step"].items():
            step[content] = [next_state, verdict, says, (list(invalidates) if invalidates else None)]
        states[state] = {"options": opts, "step": step}
    return {
        "trap": world.trap,
        "D": world.D,
        "k": world.k,
        "w": world.w,
        "form": world.form,
        "budget": world.budget,
        "states": states,
    }


def all_worlds_as_dicts():
    """`worlds`, sorted by (trap, D, k, w, form), as the fingerprint's JSON list."""
    ordered = sorted(worlds(), key=lambda wd: (wd.trap, wd.D, wd.k, wd.w, wd.form))
    return [_world_to_dict(wd) for wd in ordered]


def fingerprint():
    """sha256 of json.dumps(all_worlds_as_dicts(), sort_keys=True, separators=(",", ":"))."""
    blob = json.dumps(all_worlds_as_dicts(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
