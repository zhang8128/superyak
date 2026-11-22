"""The graded-blame fixture for north-star test 7 (docs/superpowers/specs/2026-11-22-graded-blame-fixture-design.md,
revision 3, approved at 93e08797, section "The fixture, for test 7"), with the interface Serenity proposed (all hands
d9c5f051): `generate(cell, condition, instance_index, seed_root) -> Instance`.

**One base instance per (cell, instance):** its seed is `SeedSequence([seed_root, base key, instance_index])`, the base
key coming from K, M, rho, b and s only. So A, C and D share it: the overlaps, the true values, the honest noise, the bad
source and its bias. The copier's draws (its copied items and its own noise τ·σ) come from a child seed that adds a key
of tau and q. So C and D's `reports` are identical, differing only in `chains`, and A differs from them only on the
copier's copied reports.

**Fixed here** (the spec leaves them open): σ = 0.05, true values on (0, 1), and the copier one of the K, never the bad
source, chosen from the base."""
from __future__ import annotations

import hashlib
import math
import types

import numpy as np

SIGMA = 0.05
SEED_ROOT = 20261123
BASE_AXES = ("K", "M", "rho", "b", "s")
COPY_AXES = ("tau", "q")


def _key(cell, axes):
    text = ";".join(f"{a}={cell[a]!r}" for a in axes)
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def _frozen(array):
    array.setflags(write=False)
    return array


def generate(cell, condition, instance_index, seed_root=SEED_ROOT, *, _noise=True):
    """One instance, as a read-only mapping (the module docstring and the spec). `_noise=False` is for tests only."""
    if condition not in ("A", "C", "D"):
        raise ValueError("condition is A, C or D; U feeds test 6's property check only")
    for axis in BASE_AXES:
        if axis not in cell:
            raise ValueError(f"cell needs {axis}")
    K, M, rho, b, s = int(cell["K"]), int(cell["M"]), float(cell["rho"]), float(cell["b"]), float(cell["s"])
    copying = condition in ("C", "D")
    if K < 4:
        raise ValueError("K must be 4 or more, so a copier and the bad source aren't a majority of sources")
    if copying:
        for axis in COPY_AXES:
            if axis not in cell:
                raise ValueError(f"cell needs {axis} in C and D")
    base_seed = np.random.SeedSequence([seed_root, _key(cell, BASE_AXES), instance_index])
    rng = np.random.default_rng(base_seed)
    noise = (lambda scale: rng.normal(0.0, scale)) if _noise else (lambda scale: 0.0)

    # Overlaps: items one at a time until each has two reports, then sources topped up to five (spec, "Minimums").
    seen = np.zeros((K, M), dtype=bool)
    attempts = 0
    for i in range(M):
        while True:
            attempts += 1
            row = rng.random(K) < rho
            if row.sum() >= 2:
                seen[:, i] = row
                break
    for k in range(K):
        while seen[k].sum() < 5:
            attempts += 1
            seen[k, int(rng.choice(np.flatnonzero(~seen[k])))] = True

    true_values = rng.uniform(0.0, 1.0, M)
    bad = int(rng.integers(K))
    copier = int(rng.choice([k for k in range(K) if k != bad]))  # from the base, so A, C and D agree on it
    own = np.flatnonzero(seen[bad])
    biased = sorted(int(i) for i in rng.choice(own, size=math.ceil(s * len(own)), replace=False))
    sign = float(rng.choice([-1.0, 1.0]))

    reports = np.full((K, M), np.nan)
    for k in range(K):
        for i in np.flatnonzero(seen[k]):
            reports[k, i] = true_values[i] + noise(SIGMA)
    for i in biased:
        reports[bad, i] += sign * b * SIGMA

    chains = np.full((K, M), None, dtype=object)
    copied = []
    honest_counts = {}
    copy_seed = None
    if copying:
        tau, q = float(cell["tau"]), float(cell["q"])
        copy_seed = np.random.SeedSequence([seed_root, _key(cell, BASE_AXES), instance_index, _key(cell, COPY_AXES)])
        crng = np.random.default_rng(copy_seed)
        shared = np.flatnonzero(seen[bad] & seen[copier])
        if len(shared):
            copied = sorted(int(i) for i in crng.choice(shared, size=math.ceil(q * len(shared)), replace=False))
        for i in copied:
            reports[copier, i] = reports[bad, i] + (crng.normal(0.0, tau * SIGMA) if _noise else 0.0)
            honest_counts[i] = int(sum(seen[k, i] for k in range(K) if k not in (bad, copier)))
            if condition == "C":
                chains[copier, i] = bad

    truth = types.MappingProxyType({
        "bad": bad, "copier": copier if copying else None, "biased_items": biased, "bias_sign": sign,
        "copied_items": copied, "true_values": _frozen(true_values), "honest_counts_on_copied": honest_counts})
    meta = types.MappingProxyType({
        "cell": dict(cell), "condition": condition, "realised_density": float(seen.mean()),
        "redraw_attempts": attempts, "sigma": SIGMA,
        "seeds": {"root": seed_root, "base_key": _key(cell, BASE_AXES), "instance": instance_index,
                  "copy_key": _key(cell, COPY_AXES) if copying else None}})
    return types.MappingProxyType({"reports": _frozen(reports), "sigma": SIGMA, "chains": _frozen(chains),
                                   "truth": truth, "meta": meta})
