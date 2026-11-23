"""North-star test 4, the policy half: fixed, random, adaptive by name and adaptive by content.

Written from two sections of docs/superpowers/specs/2026-11-22-north-star-test-4-design.md alone: "The contract",
whose sha256 from its heading to "## The policies" is f0971788…, and "The policies", from its heading to
"## Stage A", fixed at draft 3 with sha256 003232cd…. Nothing here was written from a world, and no world's code was
read.

Each policy is a function of `(record, options, seed)` alone and returns `(index, flags)`. `index` points into
`options`, and `flags` is a list of one-key dicts. A record is a list of entries with `turn`, `state`, `name`,
`content`, `verdict` ("pass" or "fail"), `summary` (`{"approach", "says"}`) and `observation` (`None` or
`{"invalidates": [content, ...]}`). An option is `{"name", "content"}`.

**Readings taken where the two sections leave a detail open.** Each is said here so a reader can check it:
- **The `premise` drop** covers the entries up to and including the observation's turn whose content it names. The
  contract says an observation means "earlier verdicts on those contents no longer hold", so later verdicts still
  count.
- **Adaptive by content** raises the same flags as adaptive by name ("the same, keyed by content"), plus `repeat`.
- **Random** draws its index with `rng.integers(len(options))`.
- **Thompson** draws `rng.beta(1 + passes, 1 + fails)` as one scalar call per option, in `options` order. The largest
  wins, and a tie goes to the earlier option.
- **Fixed** breaks a tie in fewest tries by the world's order, which is "the first option, in the world's order".
"""
from __future__ import annotations

from collections import Counter

import numpy as np

START = "L0"
SAYS = {"pass": "worked", "fail": "failed"}


def _arrivals(record):
    """The turns whose entry is an arrival: its state differs from the state before it (the previous entry's, or
    "L0" for the first entry). The start is the first arrival at "L0", at turn 0."""
    arrived, before = [(0, START)], START
    for entry in record:
        if entry["state"] != before:
            arrived.append((entry["turn"], entry["state"]))
        before = entry["state"]
    return arrived


def _flags(record):
    """The flags both adaptive policies raise at this call: `cycle` on an arrival after the first at its state,
    `contradiction` and `premise` once, at the call just after their turn."""
    flags = []
    if not record:
        return flags
    last = record[-1]
    arrived = _arrivals(record)
    if arrived[-1][0] == last["turn"]:                                    # this call is the call on an arrival
        if sum(1 for _, state in arrived if state == last["state"]) > 1:
            flags.append({"cycle": last["state"]})
    if last["summary"]["says"] != SAYS[last["verdict"]]:
        flags.append({"contradiction": last["turn"]})
    if last["observation"] is not None:
        flags.append({"premise": last["turn"]})
    return flags


def _counts(record, key):
    """Passes and fails per key, from `verdict` only, after every observation's drop: entries up to and including
    an observation's turn whose content it names leave the counts."""
    dropped = set()
    for entry in record:
        if entry["observation"] is not None:
            named = set(entry["observation"]["invalidates"])
            dropped |= {e["turn"] for e in record if e["turn"] <= entry["turn"] and e["content"] in named}
    passes, fails = Counter(), Counter()
    for entry in record:
        if entry["turn"] in dropped:
            continue
        (passes if entry["verdict"] == "pass" else fails)[entry[key]] += 1
    return passes, fails


def _thompson(record, options, seed, key):
    passes, fails = _counts(record, key)
    rng = np.random.default_rng([seed, len(record), 1])
    draws = [rng.beta(1 + passes[o[key]], 1 + fails[o[key]]) for o in options]
    return int(np.argmax(draws))


def _require(options):
    if not options:
        raise ValueError("A policy needs at least one option")


def fixed(record, options, seed):
    """The first option, in the world's order, with the fewest tries by name in the whole record. No flags."""
    _require(options)
    tries = Counter(entry["name"] for entry in record)
    fewest = min(tries[o["name"]] for o in options)
    return next(i for i, o in enumerate(options) if tries[o["name"]] == fewest), []


def random(record, options, seed):
    """One uniform index from a generator built for this call. No memory, no flags."""
    _require(options)
    return int(np.random.default_rng([seed, len(record)]).integers(len(options))), []


def adaptive_name(record, options, seed):
    """Thompson sampling keyed by name, on verdicts only, with the cycle, contradiction and premise flags."""
    _require(options)
    return _thompson(record, options, seed, "name"), _flags(record)


def adaptive_content(record, options, seed):
    """Thompson sampling keyed by content, with adaptive_name's flags, plus `repeat` for each option whose content
    was tried under a different name from the one it's offered under now."""
    _require(options)
    names = {}
    for entry in record:
        names.setdefault(entry["content"], set()).add(entry["name"])
    repeats = [{"repeat": o["content"]} for o in options if names.get(o["content"], set()) - {o["name"]}]
    seen, unique = set(), []
    for flag in repeats:
        if flag["repeat"] not in seen:
            seen.add(flag["repeat"])
            unique.append(flag)
    return _thompson(record, options, seed, "content"), _flags(record) + unique


POLICIES = {"fixed": fixed, "random": random, "adaptive_name": adaptive_name, "adaptive_content": adaptive_content}
SEEDS = range(20)
